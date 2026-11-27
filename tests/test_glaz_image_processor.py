"""Native image processing must preserve the original pixels and latency."""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Glaz"))
import image_processor


class LineMaskTests(unittest.TestCase):
    @unittest.skipUnless(image_processor._HAS_OPENCV, "OpenCV is not installed")
    def test_native_mask_matches_python_scan(self):
        rng = np.random.default_rng(11)
        for shape in ((3, 3), (7, 13), (13, 7), (48, 64)):
            for length in (1, 3, 5):
                for _ in range(10):
                    pixels = np.where(rng.random(shape) < 0.4, 0, 255).astype(np.uint8)
                    with patch.object(image_processor, "_HAS_OPENCV", False):
                        expected = image_processor.ImageProcessor._mask_solid_lines(
                            pixels, 128, length
                        )
                    actual = image_processor.ImageProcessor._mask_solid_lines(
                        pixels, 128, length
                    )
                    np.testing.assert_array_equal(actual, expected)

    @unittest.skipUnless(image_processor._HAS_OPENCV, "OpenCV is not installed")
    def test_full_frame_mask_is_fast(self):
        pixels = np.full((768, 1024), 255, dtype=np.uint8)
        pixels[::9, :] = 0
        pixels[:, ::11] = 0
        started = time.perf_counter()
        image_processor.ImageProcessor._mask_solid_lines(pixels, 128, 3)
        self.assertLess(time.perf_counter() - started, 0.75)


class ColorPeaksTests(unittest.TestCase):
    @unittest.skipUnless(image_processor._HAS_OPENCV, "OpenCV is not installed")
    def test_native_gradients_match_numpy_for_supported_image_modes(self):
        rng = np.random.default_rng(19)
        for mode, channels in (("L", 0), ("LA", 2), ("RGB", 3), ("RGBA", 4)):
            for shape in ((1, 1), (1, 9), (9, 1), (12, 17)):
                size = shape + ((channels,) if channels else ())
                pixels = rng.integers(0, 256, size, dtype=np.uint8)
                image = Image.fromarray(pixels, mode=mode)
                for threshold in (0, 100, 255, 500):
                    for invert in (False, True):
                        with patch.object(image_processor, "_HAS_OPENCV", False):
                            expected = image_processor.ImageProcessor.detect_color_peaks(
                                image, threshold, invert
                            )
                        actual = image_processor.ImageProcessor.detect_color_peaks(
                            image, threshold, invert
                        )
                        np.testing.assert_array_equal(np.array(actual), np.array(expected))


if __name__ == "__main__":
    unittest.main()
