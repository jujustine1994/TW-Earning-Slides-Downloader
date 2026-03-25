import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import requests

# Import from main.py without launching the GUI
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


# ---- Mock HTML fixtures ----
MOCK_HTML_ONE_ROW = """
<html><body><table>
<tr>
  <td>2330</td>
  <td>台積電</td>
  <td>115/01/15</td>
  <td>14:00</td>
  <td>台北文華東方酒店</td>
  <td>說明會摘要</td>
  <td><a href="/nas/STR/233020260115M001.pdf">233020260115M001.pdf</a></td>
  <td><a href="/nas/STR/233020260115E001.pdf">233020260115E001.pdf</a></td>
</tr>
</table></body></html>
"""

MOCK_HTML_EMPTY = """
<html><body><table><tr><td>查無資料</td></tr></table></body></html>
"""

MOCK_HTML_NO_PDF = """
<html><body><table>
<tr>
  <td>2330</td>
  <td>台積電</td>
  <td>115/02/20</td>
  <td>10:00</td>
  <td>某地點</td>
  <td>摘要</td>
  <td></td>
  <td></td>
</tr>
</table></body></html>
"""


# ---- TestDateRangeToMonths ----
class TestDateRangeToMonths(unittest.TestCase):
    def test_single_month(self):
        result = main.date_range_to_months("20260101", "20260131")
        self.assertEqual(result, [(2026, 1)])

    def test_three_months(self):
        result = main.date_range_to_months("20150101", "20150301")
        self.assertEqual(result, [(2015, 1), (2015, 2), (2015, 3)])

    def test_year_boundary(self):
        result = main.date_range_to_months("20151101", "20160201")
        self.assertEqual(result, [(2015, 11), (2015, 12), (2016, 1), (2016, 2)])

    def test_same_month_different_days(self):
        result = main.date_range_to_months("20260115", "20260325")
        self.assertEqual(result, [(2026, 1), (2026, 2), (2026, 3)])


# ---- TestRocYear ----
class TestRocYear(unittest.TestCase):
    def test_2026(self):
        self.assertEqual(main.roc_year(2026), 115)

    def test_2015(self):
        self.assertEqual(main.roc_year(2015), 104)


# ---- TestParseRocDate ----
class TestParseRocDate(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(main.parse_roc_date("115/01/15"), "20260115")

    def test_no_padding(self):
        self.assertEqual(main.parse_roc_date("114/3/5"), "20250305")

    def test_invalid(self):
        self.assertEqual(main.parse_roc_date("baddate"), "")


# ---- TestBuildSavePath ----
class TestBuildSavePath(unittest.TestCase):
    def test_no_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main.build_save_path("20260115", "zh", tmpdir)
            expected = os.path.join(tmpdir, "20260115_zh.pdf")
            self.assertEqual(result, expected)

    def test_one_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "20260115_zh.pdf"), "w").close()
            result = main.build_save_path("20260115", "zh", tmpdir)
            expected = os.path.join(tmpdir, "20260115_zh_2.pdf")
            self.assertEqual(result, expected)

    def test_two_conflicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "20260115_zh.pdf"), "w").close()
            open(os.path.join(tmpdir, "20260115_zh_2.pdf"), "w").close()
            result = main.build_save_path("20260115", "zh", tmpdir)
            expected = os.path.join(tmpdir, "20260115_zh_3.pdf")
            self.assertEqual(result, expected)

    def test_en_lang(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main.build_save_path("20260115", "en", tmpdir)
            expected = os.path.join(tmpdir, "20260115_en.pdf")
            self.assertEqual(result, expected)


# ---- TestQueryMops ----
def _make_mock_session(html_str: str):
    """Helper：建立 mock Session，讓 session.post() 回傳指定 HTML。"""
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = html_str.encode("utf-8")
    mock_resp.raise_for_status = MagicMock()
    mock_session.post.return_value = mock_resp
    return mock_session


class TestQueryMops(unittest.TestCase):
    @patch("main.requests.Session")
    def test_one_row_with_both_links(self, MockSession):
        MockSession.return_value = _make_mock_session(MOCK_HTML_ONE_ROW)

        results = main.query_mops("sii", 2026, 1, "2330")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["date"], "20260115")
        self.assertIn("233020260115M001.pdf", results[0]["zh_url"])
        self.assertIn("233020260115E001.pdf", results[0]["en_url"])

    @patch("main.requests.Session")
    def test_empty_table_returns_empty_list(self, MockSession):
        MockSession.return_value = _make_mock_session(MOCK_HTML_EMPTY)

        results = main.query_mops("sii", 2026, 1, "2330")
        self.assertEqual(results, [])

    @patch("main.requests.Session")
    def test_row_with_no_pdf_links(self, MockSession):
        MockSession.return_value = _make_mock_session(MOCK_HTML_NO_PDF)

        results = main.query_mops("sii", 2026, 2, "2330")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["date"], "20260220")
        self.assertEqual(results[0]["zh_url"], "")
        self.assertEqual(results[0]["en_url"], "")


# ---- TestDetectMarket ----
class TestDetectMarket(unittest.TestCase):
    @patch("main.query_mops")
    def test_found_on_sii(self, mock_query):
        mock_query.return_value = [{"date": "20260115", "zh_url": "x", "en_url": ""}]
        months = [(2026, 1), (2026, 2)]
        result = main.detect_market("2330", months)
        self.assertEqual(result, "sii")

    @patch("main.query_mops")
    def test_found_on_otc(self, mock_query):
        def side_effect(market, year, month, co_id):
            if market == "sii":
                return []
            if market == "otc":
                return [{"date": "20260115", "zh_url": "x", "en_url": ""}]
            return []
        mock_query.side_effect = side_effect
        months = [(2026, 1)]
        result = main.detect_market("2330", months)
        self.assertEqual(result, "otc")

    @patch("main.query_mops")
    def test_not_found_returns_none(self, mock_query):
        mock_query.return_value = []
        months = [(2026, 1), (2026, 2)]
        result = main.detect_market("9999", months)
        self.assertIsNone(result)


# ---- TestDownloadPdf ----
class TestDownloadPdf(unittest.TestCase):
    @patch("main.requests.get")
    def test_successful_download(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=[b"PDF_CONTENT"])
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "test.pdf")
            main.download_pdf("https://example.com/test.pdf", save_path)
            self.assertTrue(os.path.exists(save_path))

    @patch("main.requests.get")
    def test_http_error_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
        mock_get.return_value = mock_resp
        with self.assertRaises(requests.exceptions.RequestException):
            main.download_pdf("https://example.com/bad.pdf", "/tmp/bad.pdf")


if __name__ == "__main__":
    unittest.main()
