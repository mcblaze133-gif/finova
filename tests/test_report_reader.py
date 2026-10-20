import unittest,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from backend import report_reader as reader

class ReaderTests(unittest.IsolatedAsyncioTestCase):
 async def test_reader_has_matching_downloads_contents_and_pages(self):
  rid='a'*32;manifest={'pages':[{'number':1,'width':595,'height':842,'file':'page-01.png','links':[{'url':'#page-1','left':10,'top':10,'width':20,'height':2},{'url':'javascript:alert(1)','left':10,'top':20,'width':20,'height':2}]}]}
  with patch.object(reader,'prepared',new=AsyncMock(return_value=({'company':'hul','export_id':'matching-export'},Path('.'),manifest))):
   response=await reader.view(rid)
  text=response.body.decode()
  self.assertIn('/excel/exports/matching-export',text);self.assertIn('/analysis-reports/'+rid+'/pdf',text)
  self.assertIn('/analysis-reports/'+rid+'/pages/1',text);self.assertIn('href="#page-1"',text)
  self.assertNotIn('javascript:',text)
 async def test_page_range_and_path_escape_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   folder=Path(t)/'pages';folder.mkdir();(Path(t)/'outside.png').write_bytes(b'outside')
   manifest={'pages':[{'file':'../outside.png'}]}
   with patch.object(reader,'prepared',new=AsyncMock(return_value=({},folder,manifest))):
    with self.assertRaises(HTTPException):await reader.page_image('a'*32,0)
    with self.assertRaises(HTTPException):await reader.page_image('a'*32,1)
 async def test_page_image_uses_only_rendered_file(self):
  with tempfile.TemporaryDirectory() as t:
   folder=Path(t);image=folder/'page-01.png';image.write_bytes(b'fixture')
   with patch.object(reader,'prepared',new=AsyncMock(return_value=({},folder,{'pages':[{'file':image.name}]}))):
    response=await reader.page_image('a'*32,1)
   self.assertEqual(Path(response.path),image);self.assertEqual(response.media_type,'image/png')
