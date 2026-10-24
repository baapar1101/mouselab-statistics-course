"""Negative tests prove invalid saved outputs cannot pass promotion checks."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
import sys
import nbformat
from validate_notebook import NAME, check

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book=nbformat.read(sys.argv[1] if len(sys.argv)>1 else NAME,4)
        cls.contract=json.loads((Path(__file__).parent/'contract.json').read_text())

    def rejected(self,mutate):
        book=deepcopy(self.book); mutate(book)
        with self.assertRaises((AssertionError,nbformat.ValidationError,ValueError)):
            check(book,self.contract,executed=True)

    def test_valid_reference(self): self.assertEqual(check(self.book,self.contract,True)['lessons'],81)
    @staticmethod
    def analysis(b): return next(c for c in b.cells if c.metadata.get('mouselab',{}).get('role')=='analysis')
    def test_unexecuted(self): self.rejected(lambda b:setattr(self.analysis(b),'execution_count',None))
    def test_missing_lesson(self): self.rejected(lambda b:b.cells.remove(next(c for c in b.cells if c.metadata.get('mouselab',{}).get('role')=='lesson')))
    def test_missing_assertions(self): self.rejected(lambda b:b.cells.remove(next(c for c in b.cells if 'validation' in c.metadata.get('tags',[]))))
    def test_error(self): self.rejected(lambda b:self.analysis(b).outputs.append(nbformat.v4.new_output('error',ename='ValueError',evalue='failure',traceback=[])))
    def test_warning(self): self.rejected(lambda b:self.analysis(b).outputs.append(nbformat.v4.new_output('stream',name='stderr',text='Warning: fixture')))
    def test_missing_interpretation(self): self.rejected(lambda b:setattr(self.analysis(b),'outputs',[o for o in self.analysis(b).outputs if 'text/markdown' not in o.get('data',{})]))
    def test_missing_figure(self): self.rejected(lambda b:setattr(self.analysis(b),'outputs',[o for o in self.analysis(b).outputs if 'image/png' not in o.get('data',{})]))

if __name__=='__main__': unittest.main(argv=[sys.argv[0]])
