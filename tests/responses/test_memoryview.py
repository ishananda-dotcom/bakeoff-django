from django.http import HttpResponse
from django.test import SimpleTestCase


class HttpResponseMemoryviewTests(SimpleTestCase):
    """Tests for HttpResponse handling of memoryview objects."""

    def test_memoryview_content(self):
        """
        HttpResponse should properly handle memoryview objects.
        When a memoryview is passed to HttpResponse, response.content
        should contain the actual binary data, not the string representation.
        """
        content = b"My Content"
        response = HttpResponse(memoryview(content))
        self.assertEqual(response.content, content)

    def test_empty_memoryview_content(self):
        """
        HttpResponse should handle empty memoryview objects.
        """
        response = HttpResponse(memoryview(b""))
        self.assertEqual(response.content, b"")

    def test_large_memoryview_content(self):
        """
        HttpResponse should handle large memoryview objects.
        """
        content = b"x" * 10000
        response = HttpResponse(memoryview(content))
        self.assertEqual(response.content, content)

    def test_memoryview_with_bytes_content(self):
        """
        HttpResponse should handle memoryview objects created from bytes.
        """
        original_bytes = b"Test Content"
        mv = memoryview(original_bytes)
        response = HttpResponse(mv)
        self.assertEqual(response.content, original_bytes)

    def test_memoryview_with_bytearray_content(self):
        """
        HttpResponse should handle memoryview objects created from bytearray.
        """
        original_bytes = b"Test Content"
        ba = bytearray(original_bytes)
        mv = memoryview(ba)
        response = HttpResponse(mv)
        self.assertEqual(response.content, original_bytes)

    def test_memoryview_slice(self):
        """
        HttpResponse should handle sliced memoryview objects.
        """
        content = b"Hello World"
        mv = memoryview(content)[0:5]
        response = HttpResponse(mv)
        self.assertEqual(response.content, b"Hello")

    def test_string_content_still_works(self):
        """
        HttpResponse should still handle string content correctly.
        """
        response = HttpResponse("My Content")
        self.assertEqual(response.content, b"My Content")

    def test_bytes_content_still_works(self):
        """
        HttpResponse should still handle bytes content correctly.
        """
        response = HttpResponse(b"My Content")
        self.assertEqual(response.content, b"My Content")
