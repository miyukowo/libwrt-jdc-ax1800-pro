"""Lightweight regression fixtures; never compile firmware or execute target code."""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class SeedRegressionTests(unittest.TestCase):
    def test_required_packages_are_explicit_in_both_seeds(self):
        for variant in ('nowifi', 'wifi'):
            text = (REPO / f'configs/jdc-ax1800-pro-{variant}.config').read_text()
            for package in ('kmod-tun', 'kmod-zram', 'kmod-lib-zstd', 'zram-swap',
                            'kmod-wireguard', 'wireguard-tools', 'luci-proto-wireguard'):
                with self.subTest(variant=variant, package=package):
                    self.assertIn(f'CONFIG_PACKAGE_{package}=y', text.splitlines())

# The validator is imported lazily so the seed regression can run before it exists.
import contextlib
import importlib.util
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile


def validator():
    spec = importlib.util.spec_from_file_location('firmware_validation', REPO / 'scripts/validate-firmware.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidationTests(unittest.TestCase):
    def setUp(self):
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.v = validator()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name)
        self.config = {key: 'y' for key in self.v.required_symbols()}
        self.config.update({
            'CONFIG_TARGET_BOARD': '"qualcommax"',
            'CONFIG_TARGET_SUBTARGET': '"ipq60xx"',
            'CONFIG_TARGET_PROFILE': '"DEVICE_jdcloud_re-ss-01"',
            'CONFIG_TARGET_ARCH_PACKAGES': '"aarch64_cortex-a53"',
        })
        self.config.update({f'CONFIG_BUSYBOX_DEFAULT_{name}': 'y' for name in self.v.SWAP_APPLETS})
        self.out = self.tree / 'bin/targets/qualcommax/ipq60xx'
        self.out.mkdir(parents=True)
        self.manifest = {p: '1-r1' for p in self.v.REQUIRED_PACKAGES}
        self.manifest['kernel'] = '9.9.999~fixtureabi-r1'
        self.prefix = 'fixture-qualcommax-ipq60xx-jdcloud_re-ss-01'
        self.image = self.out / (self.prefix + '-squashfs-sysupgrade.bin')
        self.image.write_bytes(b'fixture image')
        self.profile = {'image_prefix': self.prefix, 'supported_devices': ['jdcloud,re-ss-01'],
                        'images': [{'type': 'sysupgrade', 'filesystem': 'squashfs',
                                    'name': self.image.name,
                                    'sha256': hashlib.sha256(self.image.read_bytes()).hexdigest()}]}
        self.metadata = {'target': 'qualcommax/ipq60xx', 'arch_packages': 'aarch64_cortex-a53',
                         'linux_kernel': {'version': '9.9.999', 'vermagic': 'fixtureabi', 'release': '1'},
                         'profiles': {'jdcloud_re-ss-01': self.profile}}
        self.save_profile()
        self.save_manifest()
        self.packages = self.out / 'packages'
        self.packages.mkdir()
        for p, ver in self.manifest.items():
            info = {'name': p, 'version': ver, 'arch': self.v.ARCH,
                    'depends': ['kernel='+self.manifest['kernel']] if p.startswith('kmod-') else []}
            (self.packages / f'{p}-{ver}.apk').write_text(json.dumps({'info': info}))
        # Only the external metadata dumper is stubbed; these are JSON fixtures,
        # not APK binaries. Production always uses LiBwrt's compiled host apk.
        apk = self.tree / 'staging_dir/host/bin/apk'
        apk.parent.mkdir(parents=True)
        apk.write_text('#!/bin/sh\nif [ "$1 $2" = "--allow-untrusted verify" ]; then test -s "$3"; exit; fi\n[ "$1 $2 $3" = "adbdump --format json" ] || exit 1\ncat "$4"\n')
        apk.chmod(0o755)

    def save_profile(self):
        (self.out / 'profiles.json').write_text(json.dumps(self.metadata))

    def save_manifest(self):
        (self.out / (self.prefix + '.manifest')).write_text(''.join(
            f'{p} - {ver}\n' for p, ver in self.manifest.items()))

    def test_valid_config(self):
        self.v.validate_config(self.config, 'NOWIFI')
        self.v.validate_config(self.config, 'WIFI')

    def test_mandatory_packages_cannot_be_missing_disabled_or_module(self):
        for package in self.v.REQUIRED_PACKAGES:
            for value in (None, 'n', 'm'):
                with self.subTest(package=package, value=value):
                    config = self.config.copy()
                    config[f'CONFIG_PACKAGE_{package}'] = value
                    with self.assertRaisesRegex(self.v.ValidationError, package):
                        self.v.validate_config(config, 'NOWIFI')

    def test_wrong_device_or_arch_is_rejected(self):
        for key in ('CONFIG_TARGET_PROFILE', 'CONFIG_TARGET_ARCH_PACKAGES'):
            with self.subTest(key=key):
                config = dict(self.config, **{key: '"other"'})
                with self.assertRaises(self.v.ValidationError):
                    self.v.validate_config(config, 'NOWIFI')

    def test_nowifi_rejects_wireless_but_wifi_accepts_it(self):
        for p in ('kmod-ath11k', 'kmod-mac80211', 'kmod-cfg80211', 'hostapd-common',
                  'wpad-openssl', 'wifi-scripts', 'ath11k-firmware-ipq6018',
                  'ipq-wifi-jdcloud_re-ss-01', 'kmod-qca-nss-drv-wifi-meshmgr'):
            config = dict(self.config, **{f'CONFIG_PACKAGE_{p}': 'y'})
            with self.subTest(package=p):
                with self.assertRaisesRegex(self.v.ValidationError, p):
                    self.v.validate_config(config, 'NOWIFI')
                self.v.validate_config(config, 'WIFI')

    def test_busybox_default_and_custom_branches(self):
        config = dict(self.config, CONFIG_BUSYBOX_CONFIG_SWAPON='n')
        self.v.validate_config(config, 'NOWIFI')
        config['CONFIG_BUSYBOX_CUSTOM'] = 'y'
        with self.assertRaisesRegex(self.v.ValidationError, 'BUSYBOX_CONFIG_SWAPON'):
            self.v.validate_config(config, 'NOWIFI')
        config.update({f'CONFIG_BUSYBOX_CONFIG_{p}': 'y' for p in self.v.SWAP_APPLETS})
        self.v.validate_config(config, 'NOWIFI')

    def test_zstd_and_nss_selection_required(self):
        for key in ('CONFIG_KERNEL_ZRAM_BACKEND_ZSTD', 'CONFIG_KERNEL_ZRAM_DEF_COMP_ZSTD',
                    'CONFIG_NSS_FIRMWARE_VERSION_12_1'):
            config = dict(self.config, **{key: 'n'})
            with self.subTest(key=key), self.assertRaisesRegex(self.v.ValidationError, key):
                self.v.validate_config(config, 'NOWIFI')

    def test_correct_profile_and_manifest(self):
        self.v.image_context(self.tree, 'NOWIFI')

    def test_manifest_missing_package_fails(self):
        del self.manifest['kmod-tun']
        self.save_manifest()
        with self.assertRaisesRegex(self.v.ValidationError, 'kmod-tun'):
            self.v.image_context(self.tree, 'NOWIFI')

    def test_wrong_profile_cannot_be_satisfied_by_other_manifest(self):
        self.metadata['profiles'] = {'other': self.profile}
        self.save_profile()
        with self.assertRaises(self.v.ValidationError):
            self.v.image_context(self.tree, 'NOWIFI')

    def test_manifest_wireless_rejected_for_nowifi(self):
        self.manifest['hostapd-common'] = '1-r1'
        self.save_manifest()
        with self.assertRaisesRegex(self.v.ValidationError, 'hostapd-common'):
            self.v.image_context(self.tree, 'NOWIFI')

    def test_image_digest_mismatch_fails(self):
        self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(self.v.ValidationError, 'SHA256'):
            self.v.image_context(self.tree, 'NOWIFI')

    def test_flat_archive_and_required_apks(self):
        apks = self.v.collect_apks(self.tree)
        self.v.require_apks(apks, self.manifest)
        archive = self.out / 'Packages.tar.gz'
        self.v.write_archive(archive, apks)
        self.v.validate_archive(archive, apks, self.manifest)
        with tarfile.open(archive) as t:
            self.assertIn('packages/kmod-tun-1-r1.apk', t.getnames())

    def test_missing_apk_and_wrong_version_fail(self):
        (self.packages / 'kmod-tun-1-r1.apk').rename(self.packages / 'kmod-tun-2-r1.apk')
        with self.assertRaisesRegex(self.v.ValidationError, 'kmod-tun-1-r1.apk'):
            self.v.require_apks(self.v.collect_apks(self.tree), self.manifest)

    def test_apk_metadata_mismatch_fails_despite_correct_filename(self):
        path = self.packages / 'kmod-tun-1-r1.apk'
        original = json.loads(path.read_text())
        for key, value in [('name', 'other'), ('version', '2-r1'), ('arch', 'other'), ('depends', ['kernel=otherabi'])]:
            changed = {'info': dict(original['info'], **{key: value})}
            path.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(self.v.ValidationError):
                self.v.validate_apk_metadata(self.tree, self.v.collect_apks(self.tree), self.manifest)

    def test_unreadable_apk_fails(self):
        (self.packages / 'kmod-tun-1-r1.apk').write_text('not an APK')
        with self.assertRaises(ValueError):
            self.v.validate_apk_metadata(self.tree, self.v.collect_apks(self.tree), self.manifest)

    def test_feed_collection_rejects_conflicting_names(self):
        feed = self.tree / 'bin/packages/aarch64_cortex-a53/base'
        feed.mkdir(parents=True)
        (feed / 'kmod-tun-1-r1.apk').write_bytes(b'conflict')
        with self.assertRaisesRegex(self.v.ValidationError, 'collision'):
            self.v.collect_apks(self.tree)

    def test_wrong_architecture_feed_is_ignored(self):
        other = self.tree / 'bin/packages/other/base'
        other.mkdir(parents=True)
        (other / 'wrong-1.apk').write_bytes(b'wrong')
        self.assertNotIn('wrong-1.apk', self.v.collect_apks(self.tree))

    def test_archive_missing_or_corrupt_package_fails(self):
        apks = self.v.collect_apks(self.tree)
        for corrupt in (False, True):
            archive = self.out / 'Packages.tar.gz'
            with tarfile.open(archive, 'w:gz') as t:
                for name, path in apks.items():
                    if name.startswith('kmod-tun-'):
                        if corrupt:
                            data = b'changed'
                            info = tarfile.TarInfo('packages/'+name)
                            info.size = len(data)
                            t.addfile(info, io.BytesIO(data))
                        continue
                    t.add(path, arcname='packages/'+name)
            with self.subTest(corrupt=corrupt), self.assertRaises(self.v.ValidationError):
                self.v.validate_archive(archive, apks, self.manifest)

    def root_fixture(self):
        root = self.tree / 'fixture-root'
        kernel = self.tree / 'fixture-kernel'
        root.mkdir()
        kernel.mkdir()
        kconf = {key: 'y' for key in self.v.KERNEL_REQUIRED}
        kconf.update({key: 'm' for key in self.v.MODULES})
        kconf['CONFIG_ZRAM_DEF_COMP'] = '"zstd"'
        (kernel / '.config').write_text(''.join(f'{k}={v}\n' for k, v in kconf.items()))
        (kernel / '.vermagic').write_text('fixtureabi\n')
        release = kernel / 'include/config/kernel.release'
        release.parent.mkdir(parents=True)
        release.write_text('9.9.999\n')
        for key, path in self.v.MODULES.items():
            built = kernel / path
            built.parent.mkdir(parents=True, exist_ok=True)
            built.write_bytes(b'fixture module')
            installed = root / 'lib/modules/9.9.999' / built.name
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_bytes(b'fixture module')
        installed = root / 'lib/apk/db/installed'
        installed.parent.mkdir(parents=True)
        installed.write_text(''.join(
            f'P:{p}\nV:{ver}\nD:kernel={self.manifest["kernel"]}\n\n'
            for p, ver in self.manifest.items()))
        init = root / 'etc/init.d/zram'
        init.parent.mkdir(parents=True)
        init.write_text('#!/bin/sh /etc/rc.common\nSTART=15\n')
        init.chmod(0o755)
        link = root / 'etc/rc.d/S15zram'
        link.parent.mkdir()
        link.symlink_to('../init.d/zram')
        defaults = root / self.v.ZRAM_DEFAULTS
        defaults.parent.mkdir()
        shutil.copy2(REPO / 'files' / self.v.ZRAM_DEFAULTS, defaults)
        modules = root / 'etc/modules.d'
        modules.mkdir()
        (modules / '30-tun').write_text('tun\n')
        (modules / '20-zram').write_text('zsmalloc\nzram\n')
        return root, kernel

    def test_rootfs_and_kernel_outputs(self):
        root, kernel = self.root_fixture()
        self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def test_missing_rootfs_module_init_or_defaults_fails(self):
        for rel in ('lib/modules/9.9.999/tun.ko', 'etc/rc.d/S15zram', self.v.ZRAM_DEFAULTS):
            with self.subTest(path=rel):
                root, kernel = self.root_fixture()
                (root / rel).unlink()
                with self.assertRaises(self.v.ValidationError):
                    self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])
                shutil.rmtree(root)
                shutil.rmtree(kernel)

    def test_builtin_requires_modules_builtin_evidence(self):
        root, kernel = self.root_fixture()
        path = self.v.MODULES['CONFIG_TUN']
        config = kernel / '.config'
        config.write_text(config.read_text().replace('CONFIG_TUN=m', 'CONFIG_TUN=y'))
        (root / 'lib/modules/9.9.999/tun.ko').unlink()
        (kernel / path).unlink()
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])
        (kernel / 'modules.builtin').write_text('kernel/'+path+'\n')
        self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def test_installed_metadata_kernel_abi_mismatch_fails(self):
        root, kernel = self.root_fixture()
        db = root / 'lib/apk/db/installed'
        db.write_text(db.read_text().replace('D:kernel=9.9.999~fixtureabi-r1', 'D:kernel=otherabi'))
        with self.assertRaisesRegex(self.v.ValidationError, 'ABI'):
            self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def test_built_kernel_abi_must_match_profile_and_manifest(self):
        root, kernel = self.root_fixture()
        (kernel / '.vermagic').write_text('otherabi\n')
        with self.assertRaisesRegex(self.v.ValidationError, 'ABI'):
            self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])
        (kernel / '.vermagic').write_text('fixtureabi\n')
        self.metadata['linux_kernel']['release'] = '2'
        with self.assertRaisesRegex(self.v.ValidationError, 'ABI'):
            self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs tools unavailable')
    def test_extract_root_from_exact_sysupgrade_image(self):
        root, kernel = self.root_fixture()
        squash = self.tree / 'root.squashfs'
        subprocess.run(['mksquashfs', str(root), str(squash), '-noappend', '-processors', '1', '-quiet'],
                       check=True, stdout=subprocess.DEVNULL)
        with tarfile.open(self.image, 'w') as t:
            t.add(squash, arcname='sysupgrade-jdcloud_re-ss-01/root')
        # append-metadata adds trailing data; tar reader must still accept the image.
        with self.image.open('ab') as f:
            f.write(b'fixture fwtool trailer')
        with tempfile.TemporaryDirectory() as tmp:
            extracted = self.v.extract_rootfs(self.image, Path(tmp))
            self.v.validate_rootfs(extracted, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def test_kernel_compressor_and_swap_are_mandatory(self):
        root, kernel = self.root_fixture()
        original = (kernel / '.config').read_text()
        for key in self.v.KERNEL_REQUIRED:
            with self.subTest(key=key):
                (kernel / '.config').write_text(original.replace(key+'=y', key+'=n'))
                with self.assertRaisesRegex(self.v.ValidationError, key):
                    self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def test_manifest_and_installed_db_must_agree(self):
        root, kernel = self.root_fixture()
        db = root / 'lib/apk/db/installed'
        db.write_text(db.read_text().replace('P:kmod-tun\nV:1-r1', 'P:kmod-tun\nV:2-r1'))
        with self.assertRaisesRegex(self.v.ValidationError, 'differs from firmware manifest'):
            self.v.validate_rootfs(root, kernel, self.manifest, 'NOWIFI', self.metadata['linux_kernel'])

    def run_cli(self, stage, *extra, success=True):
        result = subprocess.run([
            sys.executable, str(REPO / 'scripts/validate-firmware.py'), stage,
            '--tree', str(self.tree), '--variant', 'NOWIFI', *map(str, extra),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout+result.stderr)
        return result

    def config_fixture(self):
        (self.tree / '.config').write_text(''.join(f'{k}={v}\n' for k, v in self.config.items()))
        # Read-only git provenance from the test checkout; no git writes or commits.
        (self.tree / '.git').symlink_to(REPO / '.git', target_is_directory=True)
        requested = REPO / 'configs/jdc-ax1800-pro-nowifi.config'
        self.run_cli('config', '--requested', requested)

    def test_config_changed_after_gate_fails(self):
        self.config_fixture()
        with (self.tree / '.config').open('a') as stream:
            stream.write('# later config modification\n')
        result = self.run_cli('artifacts', success=False)
        self.assertIn('changed after final configuration validation', result.stderr)

    def test_requested_variant_mismatch_fails(self):
        self.config_fixture()
        result = self.run_cli('config', '--requested', REPO / 'configs/jdc-ax1800-pro-wifi.config', success=False)
        self.assertIn('seed variant mismatch', result.stderr)

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs tools unavailable')
    def test_full_cli_config_image_archive_roundtrip(self):
        self.config_fixture()
        root, kernel = self.root_fixture()
        actual_kernel = self.tree / 'build_dir/target-fixture/linux-qualcommax_ipq60xx/linux-9.9.999'
        actual_kernel.parent.mkdir(parents=True)
        kernel.rename(actual_kernel)
        squash = self.tree / 'root.squashfs'
        subprocess.run(['mksquashfs', str(root), str(squash), '-noappend', '-processors', '1', '-quiet'],
                       check=True, stdout=subprocess.DEVNULL)
        with tarfile.open(self.image, 'w') as archive:
            archive.add(squash, arcname='sysupgrade-jdcloud_re-ss-01/root')
        self.profile['images'][0]['sha256'] = self.v.digest(self.image)
        self.save_profile()
        # Archive creation requires the image gate to have succeeded first.
        self.run_cli('archive', success=False)
        self.run_cli('artifacts', '--kernel-dir', actual_kernel)
        self.run_cli('archive')
        report = json.loads((self.out / 'build-validation.json').read_text())
        self.assertEqual(report['archive_validation'], 'passed')
        self.assertEqual(report['variant'], 'NOWIFI')
        self.assertEqual(report['archive_sha256'], self.v.digest(self.out / 'Packages.tar.gz'))
        self.v.validate_archive(self.out / 'Packages.tar.gz', self.v.collect_apks(self.tree), self.manifest)
        # Metadata edits after image validation cannot reuse an earlier successful report.
        with (self.out / 'profiles.json').open('a') as stream:
            stream.write(' ')
        result = self.run_cli('archive', success=False)
        self.assertIn('report is stale', result.stderr)


class InitializationTests(unittest.TestCase):
    def test_uci_defaults_sets_only_zram_algorithm(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            calls = temp / 'calls'
            uci = temp / 'uci'
            uci.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UCI_CALLS"\n')
            uci.chmod(0o755)
            environment = dict(os.environ, PATH=tmp+':'+os.environ['PATH'], UCI_CALLS=str(calls))
            result = subprocess.run(['sh', str(REPO / 'files/etc/uci-defaults/90-zram-zstd')], env=environment)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(calls.read_text().splitlines(), [
                '-q get system.@system[0]', 'set system.@system[0].zram_comp_algo=zstd', 'commit system'])


class WorkflowTests(unittest.TestCase):
    def test_validation_gates_precede_download_and_publication(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML unavailable')
        workflow = yaml.safe_load((REPO / '.github/workflows/build-openwrt.yml').read_text())
        steps = workflow['jobs']['Build']['steps']
        names = [step.get('name') for step in steps]
        self.assertLess(names.index('Load Custom Configuration'), names.index('Resolve and Validate Final Configuration'))
        self.assertLess(names.index('Resolve and Validate Final Configuration'), names.index('Download DL Packages'))
        self.assertLess(names.index('Compile Firmware'), names.index('Validate Built Firmware'))
        self.assertLess(names.index('Validate Built Firmware'), names.index('Organize Files'))
        for step in steps:
            if step.get('name') in ('Upload Bin Directory', 'Upload Firmware To Artifact', 'Release Firmware'):
                self.assertEqual(step['if'], "steps.validate_release.outputs.status == 'success'")
                self.assertLess(names.index('Organize Files'), names.index(step['name']))
            if step.get('name') in ('Resolve and Validate Final Configuration', 'Validate Built Firmware', 'Organize Files'):
                self.assertEqual(step['shell'], 'bash')  # Actions runs explicit Bash with -e -o pipefail.
        for variant, name in [('WIFI', 'JDC-AX1800-PRO.yml'), ('NOWIFI', 'JDC-AX1800-PRO-NOWIFI.yml')]:
            caller = yaml.safe_load((REPO / '.github/workflows' / name).read_text())
            self.assertEqual(caller['jobs']['build']['with']['firmware_variant'], variant)


if __name__ == '__main__':
    unittest.main()
