from scipy import ndimage
from chromatix.ops.filters import gaussian_filter, gaussian_kernel
import numpy as np
from scipy.ndimage._filters import _gaussian_kernel1d


def test_gaussian_kernel():
    kernel_chromatix = gaussian_kernel((2.0, 2.0), truncate=100.0, shape=(5, 5))
    kernel_scipy = _gaussian_kernel1d(2.0, 0, 2)
    kernel_scipy = kernel_scipy[None, :] * kernel_scipy[:, None]
    assert np.allclose(kernel_chromatix, kernel_scipy)


def test_gaussian_filter():
    a = np.arange(5000, step=2).reshape((50, 50))
    result_scipy = ndimage.gaussian_filter(a, 2.0, mode="constant", cval=2.0)
    result_chromatix = gaussian_filter(a, (2.0, 2.0))
    # Edges are different due to 2d vs twice 1d.
    assert np.allclose(result_scipy[10:-10, 10:-10], result_chromatix[10:-10, 10:-10])
