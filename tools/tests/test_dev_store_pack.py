"""Inactive store admission pins complete data while retaining recovery boot state."""
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
import dev_store as store
spec=importlib.util.spec_from_file_location('prepare_dev_store',TOOLS/'prepare-dev-store.py')
packer=importlib.util.module_from_spec(spec);spec.loader.exec_module(packer)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class StorePackage(unittest.TestCase):
    def setUp(self):
        self.directory=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.boot,self.store=self.directory/'boot',self.directory/'store'
        self.boot.mkdir();self.store.mkdir()
        self.card=dict(schema=1,board=store.BOARD,development_only=True,
            recovery_partuuid='1234abcd-02',store_partuuid='1234abcd-03',
            recovery_boot_files={'uImage':digest(b'kernel'),store.DTB:digest(b'dtb')},
            recovery_suspend_diagnostics=True)
        boot={'DEVBOOT.JSON':store.json_bytes(self.card),'boot.cmd':b'dispatcher source',
              'boot.scr':b'dispatcher binary',**{name:b'recovery descriptor' for name in store.FLAGS},
              'systems/recovery/uImage':b'kernel','systems/recovery/'+store.DTB:b'dtb'}
        for name,data in boot.items():self.write(self.boot,name,data)
        self.prefix='systems/diag27/'
        marker=b'schema=1\nid=diag27\nkernel=6.18.54-gameshellneo26\n'
        immutable={'etc/gameshellneo/image.json':digest(b'deployment'),
                   'etc/gameshellneo/development-slot':digest(marker),'usr/bin/tool':digest(b'immutable')}
        release=dict(schema=1,board=store.BOARD,slot='diag27',kernel='6.18.54-gameshellneo26',
                     store_partuuid=self.card['store_partuuid'],source_image_sha256='a'*64,
                     source_manifest_sha256=digest(b'original image'),source_fstab_sha256=digest(b'original fstab'),
                     deployment_manifest_sha256=digest(b'deployment'),immutable_files=immutable,
                     boot_files={'uImage':digest(b'kernel'),store.DTB:digest(b'dtb'),'uInitrd':digest(b'initrd')})
        files={name:b'admin fixture' for name in store.ADMIN_FILES}
        files.update({'DEVBOOT.JSON':store.json_bytes(self.card),'RELEASES.JSON':store.json_bytes({}),
                      'assembly.json':b'assembly',self.prefix+'release.json':store.json_bytes(release),
                      self.prefix+'source-image.json':b'original image',self.prefix+'source-fstab':b'original fstab',
                      self.prefix+'boot/uImage':b'kernel',self.prefix+'boot/'+store.DTB:b'dtb',
                      self.prefix+'boot/uInitrd':b'initrd'})
        for name,data in files.items():self.write(self.store,name,data)
        for name,data in {'etc/gameshellneo/image.json':b'deployment',
                          'etc/gameshellneo/development-slot':marker,'usr/bin/tool':b'immutable'}.items():
            self.write(self.store,self.prefix+'root/'+name,data)
        self.manifest=dict(schema=1,operation='development-store-package',development_only=True,
            archive=dict(file='store.ext4.gz',bytes=100,sha256='b'*64),
            raw=dict(file='store.ext4',bytes=4*1024**3,sha256='c'*64,
                     filesystem_uuid='11111111-2222-3333-4444-555555555555'),
            source_card=dict(image='development-r4.img',bytes=8*1024**3,sha256='d'*64,receipt_sha256='e'*64),
            target=dict(parent_minimum_bytes=8*1024**3,sector_bytes=512,parent_partuuid_prefix='1234abcd',
                partitions={'boot':dict(start_sector=32768,bytes=128*1024**2,partuuid='1234abcd-01'),
                            'recovery':dict(start_sector=294912,bytes=4*1024**3-144*1024**2,partuuid='1234abcd-02'),
                            'store':dict(start_sector=8388608,bytes=4*1024**3,partuuid='1234abcd-03')}),
            card=self.card,slot=dict(id='diag27',kernel=release['kernel'],manifest_sha256=digest(files[self.prefix+'release.json']),
                **{key:release[key] for key in ('source_image_sha256','source_manifest_sha256','source_fstab_sha256','deployment_manifest_sha256')}),
            original_catalog={'diag27':dict(manifest_sha256=digest(files[self.prefix+'release.json']))},catalog={},
            boot_files={name:digest(data) for name,data in boot.items()},store_files={name:digest(data) for name,data in files.items()})

    def write(self,root,name,data):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

    def backup(self):
        parts=deepcopy(self.manifest['target']['partitions'])
        for name,part in parts.items():
            part['filesystem_uuid']='1234-ABCD' if name=='boot' else 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        regions={name:dict(file=name+'.img.gz',partuuid=parts[name]['partuuid'],raw_bytes=parts[name]['bytes'],
                          raw_sha256='1'*64,gzip_bytes=100,gzip_sha256='2'*64,source_unmounted=True,
                          verified_full_decompressed=True) for name in ('boot','store')}
        pins={name:'3'*64 for name in store.ADMIN_FILES}
        catalog={'diag26':{'manifest_sha256':'4'*64}}
        pins.update({'DEVBOOT.JSON':self.manifest['boot_files']['DEVBOOT.JSON'],
                     'RELEASES.JSON':digest(store.json_bytes(catalog)),
                     'systems/diag26/release.json':'4'*64,'systems/diag26/source-image.json':'5'*64,
                     'systems/diag26/source-fstab':'6'*64})
        return dict(schema=1,operation='development-store-backup',development_only=True,verified=True,
            root=dict(boot_id='11111111-2222-3333-4444-555555555555',root_partuuid='1234abcd-02',
                      directory_deployment=False,image_sha256='7'*64,kernel='6.18.54-gameshellneo24'),
            parent=dict(cid='8'*32,bytes=64013467648,sector_bytes=512,partuuid_prefix='1234abcd'),
            partitions=parts,regions=regions,card=self.card,catalog=catalog,
            flags={name:self.manifest['boot_files'][name] for name in store.FLAGS},store_files=pins,
            evidence=dict(admission_sha256='9'*64,checkpoint_result_sha256='a'*64,failed_import_sha256='b'*64))

    def test_complete_inactive_store_and_recovery_boot_verify_without_xattr_access(self):
        self.assertIs(store.validate_manifest(self.manifest),self.manifest)
        with patch.object(os,'getxattr',side_effect=AssertionError('old kernel cannot read security attrs')):
            self.assertIs(store.verify_store(self.store,self.manifest),self.manifest)
            self.assertIs(store.verify_boot(self.boot,self.manifest),self.manifest)
        backup=self.backup()
        self.assertIs(store.validate_backup(backup,self.manifest),backup)

    def test_bad_catalog_geometry_flags_and_source_pins_reject(self):
        changes=[lambda m:m.update(schema=True),lambda m:m['catalog'].update(diag27={}),
                 lambda m:m['target'].update(sector_bytes=True),
                 lambda m:m['target']['partitions']['store'].update(start_sector=1),
                 lambda m:m['raw'].update(bytes=True),lambda m:m['slot'].update(id='../escape'),
                 lambda m:m['boot_files'].update({'next.scr':'f'*64}),
                 lambda m:m['store_files'].pop('admin/tools/dev_bundle.py'),
                 lambda m:m['store_files'].update({'../escape':'f'*64}),
                 lambda m:m['source_card'].update(sha256='missing'),
                 lambda m:m.update(unrecognized=True)]
        for change in changes:
            value=deepcopy(self.manifest);change(value)
            with self.subTest(change=change),self.assertRaises(ValueError):store.validate_manifest(value)

    def test_original_recovery_backup_requires_full_verified_identity_and_failure_pins(self):
        changes=[lambda b:b['root'].update(directory_deployment=True),
                 lambda b:b['root'].update(root_partuuid='1234abcd-03'),
                 lambda b:b['root'].pop('image_sha256'),lambda b:b['root'].update(kernel='bad\nrelease'),
                 lambda b:b['parent'].update(cid='wrong'),lambda b:b['parent'].update(bytes=512),
                 lambda b:b['regions']['store'].update(verified_full_decompressed=False),
                 lambda b:b['regions']['boot'].update(source_unmounted=False),
                 lambda b:b['regions']['store'].update(raw_bytes=1),
                 lambda b:b['partitions']['store'].update(partuuid='99999999-03'),
                 lambda b:b['flags'].update({'good.scr':'f'*64}),lambda b:b['evidence'].pop('failed_import_sha256')]
        for change in changes:
            value=self.backup();change(value)
            with self.subTest(change=change),self.assertRaises(ValueError):store.validate_backup(value,self.manifest)

    def test_content_tampering_and_symlink_traversal_reject(self):
        immutable=self.store/self.prefix/'root/usr/bin/tool'
        immutable.write_bytes(b'changed')
        with self.assertRaises(ValueError):store.verify_store(self.store,self.manifest)
        immutable.unlink();outside=self.directory/'outside';outside.write_bytes(b'immutable')
        immutable.symlink_to(outside)
        with self.assertRaises(ValueError):store.verify_store(self.store,self.manifest)
        self.write(self.boot,'NEXT.SCR',b'recovery descriptor')
        with self.assertRaisesRegex(ValueError,'lowercase'):store.verify_boot(self.boot,self.manifest)

    def test_json_duplicates_nonfinite_oversize_and_symlink_reject(self):
        path=self.directory/'metadata.json'
        for content in (b'{"schema":1,"schema":1}',b'{"value":NaN}'):
            path.write_bytes(content)
            with self.assertRaises(ValueError):store.load_json(path)
        path.write_bytes(b'12345')
        with patch.object(store,'JSON_LIMIT',4),self.assertRaises(ValueError):store.load_json(path)
        link=self.directory/'link';link.symlink_to(path)
        with self.assertRaises(OSError):store.load_json(link)

    def test_region_copy_and_gzip_roundtrip_preserve_source_and_bounds(self):
        source=self.directory/'image';data=b'prefix'+bytes(range(256))*1024+b'suffix';source.write_bytes(data)
        raw=self.directory/'store.ext4'
        packer._copy_region(source,raw,6,len(data)-12)
        self.assertEqual(raw.read_bytes(),data[6:-6]);self.assertEqual(source.read_bytes(),data)
        archive,size,digest_value=packer._gzip(raw,self.directory/'store.ext4.gz')
        self.assertEqual((size,digest_value),(len(data)-12,digest(data[6:-6])))
        self.assertEqual(gzip.decompress((self.directory/archive['file']).read_bytes()),data[6:-6])
        with self.assertRaises(FileExistsError):packer._copy_region(source,raw,0,1)
        with self.assertRaises(ValueError):packer._copy_region(source,self.directory/'truncated',len(data),1)

    def test_ext4_superblock_size_and_uuid_are_bound_to_complete_raw_region(self):
        raw=self.directory/'filesystem.ext4';block=bytearray(1024)
        struct.pack_into('<I',block,4,8);block[56:58]=b'\x53\xef'
        block[104:120]=bytes.fromhex('11111111222233334444555555555555')
        raw.write_bytes(bytes(1024)+block+bytes(6144))
        self.assertEqual(packer._filesystem_uuid(raw),'11111111-2222-3333-4444-555555555555')
        with raw.open('ab') as stream:stream.write(b'extra')
        with self.assertRaises(ValueError):packer._filesystem_uuid(raw)

    def test_existing_or_symlinked_package_output_is_never_replaced(self):
        with self.assertRaises(FileExistsError):packer._fresh(self.store)
        alias=self.directory/'alias';alias.symlink_to(self.store,target_is_directory=True)
        with self.assertRaises(ValueError):packer._fresh(alias/'new-package')

    def test_bad_source_hash_stops_before_output_or_loop_operations(self):
        image,receipt=self.directory/'card.img',self.directory/'card.json'
        image.write_bytes(b'wrong image');receipt.write_bytes(b'{}\n')
        output=self.directory/'fresh-package'
        args=SimpleNamespace(image=image,receipt=receipt,image_sha256='0'*64,
                             receipt_sha256=store.sha(receipt),output=output)
        with patch.object(packer,'attached') as attach,self.assertRaisesRegex(ValueError,'checksum'):
            packer.prepare(args)
        attach.assert_not_called();self.assertFalse(output.exists())

    def test_source_card_receipt_must_match_actual_three_partition_mbr(self):
        image=self.directory/'card.img';receipt=self.directory/'card.json'
        header=bytearray(512);header[510:]=b'\x55\xaa'
        struct.pack_into('<I',header,440,0x1234abcd)
        for index,(name,part) in enumerate(self.manifest['target']['partitions'].items()):
            header[446+16*index:462+16*index]=struct.pack('<B3sB3sII',
                0x80 if index==0 else 0,b'\0'*3,0x0e if index==0 else 0x83,b'\0'*3,
                part['start_sector'],part['bytes']//512)
        with image.open('wb') as stream:stream.write(header);stream.truncate(8*1024**3)
        report=dict(schema=1,operation='development-card-assembly',development_only=True,
            offline_filesystem_checks='passed',recovery_root_byte_identical=True,
            reserved_bootloader_prefix_byte_identical=True,image=image.name,
            bytes=8*1024**3,sha256='d'*64,
            plan=dict(disk_id='1234abcd',output_bytes=8*1024**3,bytes=4*1024**3,
                store_start_sector=8388608,store_sectors=8388608,store_partuuid='1234abcd-03',
                recovery_start_sector=294912,recovery_sectors=8093696))
        receipt.write_bytes(store.json_bytes(report))
        real_sha=store.sha
        with patch.object(store,'sha',side_effect=lambda path:'d'*64 if path==image else real_sha(path)):
            result,target=packer._receipt(image,receipt,'d'*64,real_sha(receipt))
            self.assertEqual(target,self.manifest['target'])
            self.assertEqual(result,report)
            header[494]=1
            with image.open('r+b') as stream:stream.write(header)
            with self.assertRaisesRegex(ValueError,'three'):
                packer._receipt(image,receipt,'d'*64,real_sha(receipt))


if __name__=='__main__':unittest.main()
