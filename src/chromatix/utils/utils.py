import jax.numpy as jnp
import numpy as np
from chex import Array
from typing import Optional, Sequence, Tuple
from scipy.ndimage import distance_transform_edt  # type: ignore
import flax.linen as nn
from .shapes import _broadcast_2d_to_spatial


def next_order(val: int) -> int:
    return int(2 ** np.ceil(np.log2(val)))


def center_pad(u: jnp.ndarray, pad_width: Sequence[int], cval: float = 0) -> Array:
    """
    Symmetrically pads ``u`` with lengths specified per axis in ``n_padding``,
    which should be iterable and have the same size as ``u.ndims``.
    """
    pad = [(n, n) for n in pad_width]
    return jnp.pad(u, pad, constant_values=cval)


def center_crop(u: jnp.ndarray, crop_length: Sequence[int]) -> Array:
    """
    Symmetrically crops ``u`` with lengths specified per axis in
    ``crop_length``, which should be iterable with same size as ``u.ndims``.
    """
    crop_length = [0 if length is None else length for length in crop_length]
    crop = tuple([slice(n, size - n) for size, n in zip(u.shape, crop_length)])
    return u[crop]


def gaussian_kernel(
    sigma: Sequence[float], truncate: float = 4.0, shape: Optional[Sequence[int]] = None
) -> Array:
    """
    Creates ND Gaussian kernel of given ``sigma``.

    If ``shape`` is not provided, then the shape of the kernel is automatically
    calculated using the given truncation (the same truncation for each
    dimension) and ``sigma``. The number of dimensions is determined by the
    length of ``sigma``, which should be a 1D array.

    If ``shape`` is provided, then ``truncate`` is ignored and the result will
    have the provided ``shape``. The provided ``shape`` must be odd in all
    dimensions to ensure that there is a center pixel.

    Args:
        sigma: A 1D array whose length is the number of dimensions specifying
            the standard deviation of the Gaussian distribution in each
            dimension.
        truncate: If ``shape`` is not provided, then this float is the number
            of standard deviations for which to calculate the Gaussian. This is
            then used to determine the shape of the kernel in each dimension.
        shape: If provided, determines the ``shape`` of the kernel. This will
            cause ``truncate`` to be ignored.

    Returns:
        The ND Gaussian kernel.
    """
    _sigma = np.atleast_1d(np.array(sigma))
    if shape is not None:
        _shape = np.atleast_1d(np.array(shape))
        assert np.all(_shape % 2 != 0), "Shape must be odd in all dimensions"
        radius = ((_shape - 1) / 2).astype(np.int16)
    else:
        radius = (truncate * _sigma + 0.5).astype(np.int16)

    x = jnp.mgrid[tuple(slice(-r, r + 1) for r in radius)]
    phi = jnp.exp(-0.5 * jnp.sum((x.T / _sigma) ** 2, axis=-1))  # type: ignore
    return phi / phi.sum()


def sigmoid_taper(shape: Tuple[int, int], width: float, ndim: int = 5) -> Array:
    dist = distance_transform_edt(np.pad(np.ones((shape[0] - 2, shape[1] - 2)), 1))
    taper = 2 * (nn.sigmoid(dist / width) - 0.5)
    return _broadcast_2d_to_spatial(taper, ndim)