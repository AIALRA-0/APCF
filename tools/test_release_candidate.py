# APCF-META {"schema":1,"visibility":"public"}
"""Archive identity tests; synthetic ZIP contents are not a Core acceptance test."""
import json,tempfile,unittest,zipfile
from pathlib import Path
import release_candidate as R

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.name=f'APCF-Deploy-{R.VERSION}.zip'
        raw=b'public synthetic fixture\n'
        with zipfile.ZipFile(self.root/self.name,'w') as z:z.writestr('fixture.txt',raw)
        asset=(self.root/self.name).read_bytes()
        self.identity={'name':self.name,'bytes':len(asset),'sha256':R.digest(asset)}
        self.obj={'schema':1,'version':R.VERSION,'archive':self.identity,'files':[{'path':'fixture.txt','bytes':len(raw),'sha256':R.digest(raw)}]}
        (self.root/(self.name+'.sha256')).write_text(R.digest(asset)+'  '+self.name+'\n',encoding='ascii')
    def verify(self):
        (self.root/'RELEASE-MANIFEST.json').write_text(json.dumps(self.obj),encoding='utf-8')
        return R.verify(self.root)
    def test_public_builder_archive(self):self.assertEqual(self.verify()['files'],1)
    def test_current_source_builder_zip(self):
        self.obj['zip']=self.obj.pop('archive');self.assertEqual(self.verify()['files'],1)
    def test_ambiguous_identity_rejected(self):
        self.obj['zip']=self.identity
        with self.assertRaisesRegex(ValueError,'exactly one'):self.verify()
    def test_missing_identity_rejected(self):
        del self.obj['archive']
        with self.assertRaisesRegex(ValueError,'exactly one'):self.verify()
    def test_boolean_size_rejected(self):
        self.identity['bytes']=True
        with self.assertRaisesRegex(ValueError,'size'):self.verify()
    def test_wrong_archive_digest_rejected(self):
        self.identity['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.verify()
    def test_wrong_member_digest_rejected(self):
        self.obj['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'member content'):self.verify()
    def test_wrong_sidecar_rejected(self):
        (self.root/(self.name+'.sha256')).write_text('0'*64+'  '+self.name,encoding='ascii')
        with self.assertRaisesRegex(ValueError,'sidecar'):self.verify()

if __name__=='__main__':unittest.main()
