"""Negative tests prove invalid saved outputs cannot pass promotion checks."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
import nbformat
from validate_notebook import NAME, check

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book=nbformat.read(NAME,4)
        cls.contract=json.loads((Path(__file__).parent/'contract.json').read_text())

    def rejected(self,mutate):
        book=deepcopy(self.book); mutate(book)
        with self.assertRaises((AssertionError,nbformat.ValidationError,ValueError)):
            check(book,self.contract,executed=True)

    def test_valid_reference(self): self.assertEqual(check(self.book,self.contract,True)['lessons'],81)
    def test_unexecuted(self): self.rejected(lambda b:setattr(b.cells[1],'execution_count',None))
    def test_missing_lesson(self): self.rejected(lambda b:b.cells.pop(6))
    def test_missing_assertions(self): self.rejected(lambda b:b.cells.pop(262))
    def test_error(self): self.rejected(lambda b:b.cells[7].outputs.append(nbformat.v4.new_output('error',ename='ValueError',evalue='failure',traceback=[])))
    def test_warning(self): self.rejected(lambda b:b.cells[7].outputs.append(nbformat.v4.new_output('stream',name='stderr',text='Warning: fixture')))
    def test_missing_interpretation(self): self.rejected(lambda b:setattr(b.cells[7],'outputs',[o for o in b.cells[7].outputs if 'text/markdown' not in o.get('data',{})]))
    def test_missing_figure(self): self.rejected(lambda b:setattr(b.cells[7],'outputs',[o for o in b.cells[7].outputs if 'image/png' not in o.get('data',{})]))

if __name__=='__main__': unittest.main()
