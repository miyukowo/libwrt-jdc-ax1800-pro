#!/usr/bin/env python3
"""Fail closed on package, variant, kernel, image, or offline archive omissions.

Uses only Python's standard library and the host unsquashfs tool. No target
binaries are executed and no external packages/modules are downloaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

TARGET = 'qualcommax/ipq60xx'
ARCH = 'aarch64_cortex-a53'
PROFILE = 'jdcloud_re-ss-01'
ZRAM_DEFAULTS = 'etc/uci-defaults/90-zram-zstd'
REQUIRED_PACKAGES = (
    'kmod-tun', 'kmod-zram', 'kmod-lib-zstd', 'zram-swap',
    'kmod-crypto-acompress', 'kmod-lib-xxhash',
    'kmod-wireguard', 'wireguard-tools', 'luci-proto-wireguard',
    'kmod-qca-nss-drv', 'kmod-qca-nss-dp', 'kmod-qca-nss-ecm',
    'kmod-qca-nss-crypto', 'nss-firmware-ipq60xx',
)
SWAP_APPLETS = ('MKSWAP', 'SWAPON', 'SWAPOFF', 'FEATURE_SWAPON_DISCARD', 'FEATURE_SWAPON_PRI')
KERNEL_REQUIRED = ('CONFIG_SWAP', 'CONFIG_ZRAM_BACKEND_ZSTD', 'CONFIG_ZRAM_DEF_COMP_ZSTD')
MODULES = {
    'CONFIG_TUN': 'drivers/net/tun.ko',
    'CONFIG_WIREGUARD': 'drivers/net/wireguard/wireguard.ko',
    'CONFIG_ZRAM': 'drivers/block/zram/zram.ko',
    'CONFIG_ZSMALLOC': 'mm/zsmalloc.ko',
    'CONFIG_CRYPTO_ACOMP2': 'crypto/crypto_acompress.ko',
    'CONFIG_XXHASH': 'lib/xxhash.ko',
    'CONFIG_CRYPTO_ZSTD': 'crypto/zstd.ko',
    'CONFIG_ZSTD_COMMON': 'lib/zstd/zstd_common.ko',
    'CONFIG_ZSTD_COMPRESS': 'lib/zstd/zstd_compress.ko',
    'CONFIG_ZSTD_DECOMPRESS': 'lib/zstd/zstd_decompress.ko',
}
# Reject the wireless stack and board firmware, including future ath11k variants.
WIRELESS = re.compile(r'^(?:kmod-(?:ath(?:\d.*)?|mac80211.*|cfg80211.*)|'
                      r'ath\d+k?-firmware.*|ipq-wifi-.*|hostapd(?:-.*)?|wpad(?:-.*)?|'
                      r'wpa-supplicant(?:-.*)?|wifi-scripts|wireless-regdb|dawn|'
                      r'kmod-qca-nss-drv-wifi-.*)$')


class ValidationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return stream_digest(stream)


def stream_digest(stream):
    checksum = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        checksum.update(block)
    return checksum.hexdigest()


def read_config(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            require(key not in values, f'Duplicate config assignment: {key}')
            values[key] = value
    return values


def required_symbols():
    return tuple('CONFIG_PACKAGE_'+p for p in REQUIRED_PACKAGES) + (
        'CONFIG_TARGET_qualcommax', 'CONFIG_TARGET_qualcommax_ipq60xx',
        'CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_'+PROFILE,
        'CONFIG_USE_APK', 'CONFIG_KERNEL_SWAP', 'CONFIG_PACKAGE_busybox', 'CONFIG_KERNEL_ZRAM_BACKEND_ZSTD',
        'CONFIG_KERNEL_ZRAM_DEF_COMP_ZSTD', 'CONFIG_NSS_FIRMWARE_VERSION_12_1',
    )


def no_wireless(packages, variant):
    if variant == 'NOWIFI':
        found = sorted(p for p in packages if WIRELESS.fullmatch(p))
        require(not found, 'NOWIFI includes forbidden wireless packages: '+', '.join(found))


def validate_config(config, variant):
    errors = []
    symbols = required_symbols()
    # busybox/Makefile uses DEFAULT unless BUSYBOX_CUSTOM is enabled.
    busybox = 'CONFIG' if config.get('CONFIG_BUSYBOX_CUSTOM') == 'y' else 'DEFAULT'
    symbols += tuple(f'CONFIG_BUSYBOX_{busybox}_{p}' for p in SWAP_APPLETS)
    for key in symbols:
        value = config.get(key, '<unset>')
        print(f'  {key}={value}')
        if value != 'y':
            errors.append(f'{key}: expected y for image inclusion/support, got {value}')
    for key, expected in (
        ('CONFIG_TARGET_BOARD', '"qualcommax"'),
        ('CONFIG_TARGET_SUBTARGET', '"ipq60xx"'),
        ('CONFIG_TARGET_PROFILE', '"DEVICE_'+PROFILE+'"'),
        ('CONFIG_TARGET_ARCH_PACKAGES', '"'+ARCH+'"'),
    ):
        if config.get(key) != expected:
            errors.append(f'{key}: expected {expected}, got {config.get(key, "<unset>")}')
    devices = [k for k, v in config.items() if '_DEVICE_' in k and k.startswith('CONFIG_TARGET_') and v == 'y']
    if devices != ['CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_'+PROFILE]:
        errors.append('Expected exactly the JDCloud RE-SS-01 device selection: '+str(devices))
    if variant == 'NOWIFI':
        for key in ('CONFIG_ATH11K_NSS_SUPPORT', 'CONFIG_ATH11K_NSS_MESH_SUPPORT'):
            if config.get(key) in ('y', 'm'):
                errors.append('NOWIFI must disable '+key)
    try:
        no_wireless((k.removeprefix('CONFIG_PACKAGE_') for k, v in config.items()
                     if k.startswith('CONFIG_PACKAGE_') and v in ('y', 'm')), variant)
    except ValidationError as error:
        errors.append(str(error))
    require(not errors, '\n'.join(errors))


def read_manifest(path, variant):
    packages = {}
    for line in path.read_text().splitlines():
        fields = line.split(' - ')
        require(len(fields) == 2 and all(fields), f'Unexpected manifest entry: {line!r}')
        package, version = fields
        require(package not in packages, 'Duplicate manifest package: '+package)
        packages[package] = version
    for package in ('kernel',) + REQUIRED_PACKAGES:
        version = packages.get(package)
        print(f'  manifest: {package} - {version or "<missing>"}')
    missing = sorted(set(('kernel',) + REQUIRED_PACKAGES) - packages.keys())
    require(not missing, 'Firmware manifest missing mandatory packages: '+', '.join(missing))
    no_wireless(packages, variant)
    return packages


def image_context(tree, variant):
    out = tree / 'bin/targets' / TARGET
    metadata = json.loads((out / 'profiles.json').read_text())
    require(metadata['target'] == TARGET and metadata['arch_packages'] == ARCH, 'Wrong profiles.json target/architecture')
    require(set(metadata['profiles']) == {PROFILE}, 'Expected only profile '+PROFILE)
    profile = metadata['profiles'][PROFILE]
    require('jdcloud,re-ss-01' in profile['supported_devices'], 'Wrong supported board')
    prefix = profile['image_prefix']
    require(Path(prefix).name == prefix and prefix.endswith('-'+PROFILE), 'Unexpected image prefix')
    images = profile['images']
    selected = [entry for entry in images if entry['type'] == 'sysupgrade' and entry.get('filesystem') == 'squashfs']
    require(len(selected) == 1, 'Expected exactly one squashfs sysupgrade image for '+PROFILE)
    for entry in images:
        name = entry['name']
        require(Path(name).name == name and name.startswith(prefix+'-'), 'Unexpected profile image: '+name)
        path = out / name
        require(path.is_file() and path.stat().st_size > 0, 'Missing/empty image: '+str(path))
        require(digest(path) == entry['sha256'], 'Image SHA256 differs from profiles.json: '+name)
    manifest = read_manifest(out / (prefix+'.manifest'), variant)
    return out, metadata, manifest, out / selected[0]['name']


def collect_apks(tree):
    directories = [tree / 'bin/targets' / TARGET / 'packages']
    feeds = tree / 'bin/packages' / ARCH
    if feeds.is_dir():
        directories.extend(p for p in feeds.iterdir() if p.is_dir())
    apks = {}
    for directory in sorted(directories):
        for path in sorted(directory.glob('*.apk')):
            require(path.is_file() and path.stat().st_size > 0, 'Empty APK: '+str(path))
            if path.name in apks:
                require(digest(path) == digest(apks[path.name]), 'APK filename collision: '+path.name)
            apks[path.name] = path
    return apks


def require_apks(apks, manifest):
    missing = []
    for package in ('kernel',) + REQUIRED_PACKAGES:
        name = f'{package}-{manifest[package]}.apk'
        print('  APK: '+name+(' OK' if name in apks else ' MISSING'))
        if name not in apks:
            missing.append(name)
    require(not missing, 'Missing matching build APKs: '+', '.join(missing))


def validate_apk_metadata(tree, apks, manifest):
    apk = tree / 'staging_dir/host/bin/apk'
    require(apk.is_file() and os.access(apk, os.X_OK), 'Missing build-host APK tool: '+str(apk))
    for package in ('kernel',) + REQUIRED_PACKAGES:
        path = apks[f'{package}-{manifest[package]}.apk']
        # OpenWrt authenticates repositories via their index; locally built APKs
        # can be unsigned. This read-only verify checks payload integrity. It
        # does not install anything or relax dependency/ABI validation below.
        subprocess.run([str(apk), '--allow-untrusted', 'verify', str(path)], check=True)
        # One file per invocation: adbdump emits one JSON document per APK.
        info = json.loads(subprocess.check_output(
            [str(apk), 'adbdump', '--format', 'json', str(path)], text=True))['info']
        require(info['name'] == package and info['version'] == manifest[package],
                'APK metadata name/version mismatch: '+path.name)
        allowed_arches = {ARCH} if package.startswith('kmod-') or package in ('kernel', 'wireguard-tools') else {ARCH, 'noarch'}
        require(info['arch'] in allowed_arches, 'APK architecture mismatch: '+path.name)
        if package.startswith('kmod-'):
            require('kernel='+manifest['kernel'] in info.get('depends', []),
                    'APK kernel ABI dependency mismatch: '+path.name)
        print('  APK metadata: '+path.name+' OK')


def extract_rootfs(image, temp):
    # Read one known member, never extract arbitrary tar paths or links.
    with tarfile.open(image) as archive:
        name = 'sysupgrade-'+PROFILE+'/root'
        roots = [m for m in archive.getmembers() if m.name == name and m.isfile()]
        require(len(roots) == 1, 'Missing/ambiguous sysupgrade root member: '+name)
        squashfs = temp / 'root.squashfs'
        with archive.extractfile(roots[0]) as source, squashfs.open('wb') as dest:
            shutil.copyfileobj(source, dest)
    root = temp / 'root'
    subprocess.run(['unsquashfs', '-no-progress', '-d', str(root), str(squashfs)], check=True)
    return root


def installed_database(path):
    packages = {}
    for record in path.read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in record.splitlines() if ':' in line)
        if 'P' in fields:
            require(fields['P'] not in packages, 'Duplicate installed package: '+fields['P'])
            packages[fields['P']] = fields
    return packages


def validate_rootfs(root, kernel, manifest, variant, kernel_metadata):
    config = read_config(kernel / '.config')
    for key in KERNEL_REQUIRED:
        print(f'  kernel: {key}={config.get(key, "<unset>")}')
        require(config.get(key) == 'y', 'Kernel requires '+key+'=y')
    require(config.get('CONFIG_ZRAM_DEF_COMP') == '"zstd"', 'Kernel default compressor must be zstd')
    installed = installed_database(root / 'lib/apk/db/installed')
    # This branch's image manifest describes root.orig. Check the shipped root separately.
    require({p: f.get('V') for p, f in installed.items()} == manifest,
            'Shipped rootfs installed APK database differs from firmware manifest')
    no_wireless(installed, variant)
    for package in REQUIRED_PACKAGES:
        if package.startswith('kmod-'):
            dependencies = installed[package].get('D', '').split()
            require('kernel='+manifest['kernel'] in dependencies, 'Kernel ABI dependency mismatch: '+package)
    release = (kernel / 'include/config/kernel.release').read_text().strip()
    require(release and '/' not in release, 'Invalid built kernel release')
    vermagic = (kernel / '.vermagic').read_text().strip()
    require(vermagic and vermagic == kernel_metadata['vermagic'], 'Kernel ABI .vermagic differs from profiles.json')
    expected_kernel = f'{kernel_metadata["version"]}~{vermagic}-r{kernel_metadata["release"]}'
    require(release == kernel_metadata['version'] and manifest['kernel'] == expected_kernel,
            'Kernel release/ABI differs from manifest or profiles.json')
    builtin_file = kernel / 'modules.builtin'
    # Kbuild can list installed-style kernel/... paths; package FILES paths
    # are relative to LINUX_DIR. Accept either spelling of the exact path.
    builtins = {line.removeprefix('kernel/') for line in builtin_file.read_text().splitlines()} if builtin_file.exists() else set()
    autoload = '\n'.join(p.read_text() for p in (root / 'etc/modules.d').glob('*') if p.is_file())
    for key, relative in MODULES.items():
        value = config.get(key)
        print(f'  kernel: {key}={value or "<unset>"} ({relative})')
        require(value in ('y', 'm'), 'Kernel feature missing: '+key)
        if value == 'y':
            require(relative in builtins, 'Missing modules.builtin evidence for '+key)
            continue
        built = kernel / relative
        require(built.is_file() and built.stat().st_size > 0, 'Missing kernel module build output: '+str(built))
        module = Path(relative).name
        module_dir = root / 'lib/modules' / release
        shipped = [module_dir / (module+suffix) for suffix in ('', '.gz', '.xz', '.zst')]
        require(any(p.is_file() and p.stat().st_size > 0 for p in shipped), 'Module absent from shipped rootfs: '+module)
        if key in ('CONFIG_TUN', 'CONFIG_ZRAM', 'CONFIG_ZSMALLOC'):
            require(module[:-3] in autoload.split(), 'Missing boot autoload for '+module)
    init = root / 'etc/init.d/zram'
    require(init.is_file() and os.access(init, os.X_OK), 'Missing/executable zram init script')
    start = re.search(r'^START=(\d+)$', init.read_text(), re.M)
    require(start is not None, 'Cannot determine zram init start order')
    link = root / ('etc/rc.d/S'+start[1]+'zram')
    require(link.is_symlink() and os.readlink(link) == '../init.d/zram', 'Missing zram boot enable link')
    expected = Path(__file__).resolve().parents[1] / 'files' / ZRAM_DEFAULTS
    require((root / ZRAM_DEFAULTS).is_file() and digest(root / ZRAM_DEFAULTS) == digest(expected),
            'ZSTD UCI first-boot defaults missing or changed in shipped rootfs')
    print('  rootfs: installed metadata, ABI, modules, autoload, zram init and ZSTD defaults OK')


def write_archive(path, apks):
    # Preserve the existing release contract: a flat packages/*.apk directory.
    with tarfile.open(path, 'w:gz') as archive:
        for name, source in sorted(apks.items()):
            archive.add(source, arcname='packages/'+name, recursive=False)


def validate_archive(path, apks, manifest):
    require_apks(apks, manifest)
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        files = {m.name: m for m in members if m.isfile()}
        require(len(files) == len(members), 'Archive contains duplicate or non-file entries')
        require(set(files) == {'packages/'+n for n in apks}, 'Archive contents differ from collected build APKs')
        for name, source in sorted(apks.items()):
            with archive.extractfile(files['packages/'+name]) as stream:
                require(stream_digest(stream) == digest(source), 'Archive APK content differs: '+name)
        for package in REQUIRED_PACKAGES:
            print('  archive: packages/'+package+'-'+manifest[package]+'.apk OK')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('config', 'artifacts', 'archive'))
    parser.add_argument('--tree', required=True, type=Path)
    parser.add_argument('--variant', required=True, choices=('WIFI', 'NOWIFI'))
    parser.add_argument('--requested', type=Path)
    parser.add_argument('--kernel-dir', type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()
    print(f'Validating {args.stage}: variant={args.variant}, target={TARGET}, profile={PROFILE}')
    config_path = tree / '.config'
    config = read_config(config_path)
    stamp = tree / '.firmware-validation.json'
    if args.stage == 'config':
        require(args.requested is not None, 'config stage requires --requested seed')
        requested = args.requested.read_text()
        require(requested.splitlines()[0] == f'# === LIBWRT CONFIG VARIANT: {args.variant} ===', 'Requested seed variant mismatch')
        print('Requested feature selections:')
        for line in requested.splitlines():
            if any(line.startswith(key+'=') for key in required_symbols()):
                print('  '+line)
        print('Effective final selections:')
        validate_config(config, args.variant)
        source_commit = subprocess.check_output(['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()
        write_json(stamp, {
            'variant': args.variant, 'target': TARGET, 'profile': PROFILE,
            'ci_commit': os.environ.get('GITHUB_SHA', 'local'),
            'ci_ref': os.environ.get('GITHUB_REF', 'local'),
            'workflow_ref': os.environ.get('GITHUB_WORKFLOW_REF', 'local'),
            'source_commit': source_commit, 'requested_sha256': digest(args.requested),
            'config_sha256': digest(config_path),
        })
    else:
        validate_config(config, args.variant)
        provenance = json.loads(stamp.read_text())
        require(provenance['variant'] == args.variant and provenance['config_sha256'] == digest(config_path),
                'Configuration/variant changed after final configuration validation')
        out, metadata, manifest, image = image_context(tree, args.variant)
        apks = collect_apks(tree)
        require_apks(apks, manifest)
        validate_apk_metadata(tree, apks, manifest)
        report_path = out / 'build-validation.json'
        if args.stage == 'artifacts':
            require(args.kernel_dir is not None, 'artifacts stage requires --kernel-dir from target/linux val.LINUX_DIR')
            kernel = args.kernel_dir.resolve()
            require(kernel.is_relative_to(tree / 'build_dir'), 'Kernel directory outside this build')
            require(kernel.name == 'linux-'+metadata['linux_kernel']['version'], 'Kernel directory differs from profiles.json')
            with tempfile.TemporaryDirectory(prefix='libwrt-rootfs-') as tmp:
                root = extract_rootfs(image, Path(tmp))
                validate_rootfs(root, kernel, manifest, args.variant, metadata['linux_kernel'])
            write_json(report_path, {
                **provenance, 'profiles_sha256': digest(out / 'profiles.json'),
                'manifest_sha256': digest(out / (metadata['profiles'][PROFILE]['image_prefix']+'.manifest')),
                'images': metadata['profiles'][PROFILE]['images'],
                'required_packages': {p: manifest[p] for p in REQUIRED_PACKAGES},
                'artifact_validation': 'passed',
            })
        else:
            report = json.loads(report_path.read_text())
            require(report['artifact_validation'] == 'passed' and report['config_sha256'] == digest(config_path)
                    and report['profiles_sha256'] == digest(out / 'profiles.json')
                    and report['manifest_sha256'] == digest(out / (metadata['profiles'][PROFILE]['image_prefix']+'.manifest')),
                    'Artifact validation report is stale')
            archive = out / 'Packages.tar.gz'
            write_archive(archive, apks)
            validate_archive(archive, apks, manifest)
            report.update({'archive_validation': 'passed', 'archive_sha256': digest(archive), 'archive_apks': len(apks)})
            write_json(report_path, report)
    print(f'PASS: {args.stage} validation ({args.variant})')


if __name__ == '__main__':
    try:
        main()
    except (ValidationError, OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        print('ERROR: firmware validation failed: '+str(error), file=sys.stderr)
        sys.exit(1)
