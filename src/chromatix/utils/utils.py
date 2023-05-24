import jax.numpy as jnp
import numpy as np
from chex import Array, PRNGKey
from einops import rearrange
from typing import Any, Optional, Sequence, Tuple, Union
from dataclasses import dataclass


@dataclass
class Trainable:
    """
    Wrapper class to signal to a Chromatix element that ``val`` should be the
    initialization for a trainable parameter.
    """

    val: Any


def trainable(x: Any, rng: bool = True) -> Trainable:
    """
    Returns ``x`` wrapped in a ``Trainable`` object to signal to a
    Chromatix element that ``x`` should be used to initialize a trainable
    parameter. If ``x`` is already a function, then this function will be
    used as the initializer. If ``x`` is a function that does not accept a
    ``jax.random.PRNGKey``, then setting ``rng`` to ``False`` will wrap ``x``
    so that the arguments for ``x`` are accepted after the ``PRNGKey`` argument.
    This is useful since many Chromatix functions you might want to use as
    initialization functions don't accept ``PRNGKey`` arguments. Note that this
    argument does not matter if ``x`` is already an ``Array`` that can be used
    as an initialization directly.

    When a supported Chromatix element is constructed with this wrapper as its
    attribute, it will automatically turn that attribute into a parameter to
    be optimized. Thus, this function is a convenient way to set the attribute
    of an optical element in Chromatix as a trainable parameter initialized
    to the value defined by ``x``. Any element that has potentially trainable
    parameters will be documented as such.

    For example, we can initialize a trainable phase mask (allowing for the
    optimization of the pixels of the phase mask for arbitrary tasks) with this
    function in two different ways:

    ```python
    from chromatix.utils import trainable
    from chromatix.functional import potato_chip
    from chromatix.elements import PhaseMask

    phase_mask = PhaseMask(
        phase=trainable(
            potato_chip(
                shape=(3840, 3840),
                spacing=0.3,
                wavelength=0.5,
                n=1.33,
                f=100,
                NA=0.8
            )
        )
    )
    params = phase_mask.init()
    ```

    This example directly calls ``potato_chip`` to create a trainable phase
    mask with the given shape. If there is a mismatch between the shape of an
    incoming ``Field`` and the shape of the ``phase``, then an error will occur
    at runtime. For many applications, the shape of the ``Field`` will be known
    and fixed, so this style of initialization is convenient. The second way is
    slightly more complex but also more robust to these shape issues, and does
    not require declaring the shapes twice:

    ```python
    from chromatix.utils import trainable
    from chromatix.functional import potato_chip
    from chromatix.elements import PhaseMask
    from functools import partial

    phase_mask = PhaseMask(
        phase=trainable(
            partial(
                potato_chip, spacing=0.3, wavelength=0.5, n=1.33, f=100, NA=0.8
            ),
            rng=False
        )
    )
    ```

    When ``PhaseMask`` initializes its parameters, it automatically passes
    a ``jax.random.PRNGKey`` and the spatial shape of the input ``Field``,
    which were ignored in the previous example because the initial ``phase``
    was an ``Array`` constructed by ``potato_chip``. This example uses
    ``functools.partial`` to create a phase mask initialization function that
    only accepts a shape, which is wrapped by ``trainable`` to also accept
    a ``jax.random.PRNGKey`` as its first argument. Now, when ``PhaseMask``
    initializes its parameters, it will call this initialization function,
    which uses the shape of the input ``Field`` to calculate the initial phase.
    This matches the signature of the common ``jax.nn.initializers``, which
    also accept a ``jax.random.PRNGKey`` and a shape.

    Args:
        x: The value that will be used to initialize the trainable
            parameter.
        rng: Whether the initializer function ``x`` needs a ``PRNGKey`` or not.
            If ``True``, assumes that the function ``x`` has a ``PRNGKey`` as
            its first argument, and does not modify ``x``. If ``False``, wraps
            the initializer function ``x`` to ignore the ``PRNGKey`` argument
            passed by Flax. If ``x`` is not callable, then this argument doesn't
            matter and is ignored. Defaults to ``True``.

    Returns:
        A function that takes a ``jax.random.PRNGKey`` as its first parameter.
    """
    init = x
    if callable(x) and not rng:

        def no_rng_x(key: PRNGKey, *args, **kwargs) -> Array:
            return x(*args, **kwargs)

        init = no_rng_x
    return Trainable(init)


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


def create_grid(shape: Tuple[int, int], spacing: Union[float, Array]) -> Array:
    """
    Args:
        shape: The shape of the grid, described as a tuple of
            integers of the form (H W).
        spacing: The spacing of each pixel in the grid, either a single float
            for square pixels or an array of shape `(2 1)` for non-square
            pixels.
    """
    half_size = jnp.array(shape) / 2
    spacing = jnp.atleast_1d(spacing)
    if spacing.size == 1:
        spacing = jnp.concatenate([spacing, spacing])
    assert spacing.size == 2, "Spacing must be either single float or have shape (2,)"
    spacing = rearrange(spacing, "d -> d 1 1", d=2)
    # @copypaste(Field): We must use meshgrid instead of mgrid here
    # in order to be jittable
    grid = jnp.meshgrid(
        jnp.linspace(-half_size[0], half_size[0] - 1, num=shape[0]) + 0.5,
        jnp.linspace(-half_size[1], half_size[1] - 1, num=shape[1]) + 0.5,
        indexing="ij",
    )
    grid = spacing * jnp.array(grid)
    return grid


def grid_spatial_to_pupil(grid: Array, f: float, NA: float, n: float) -> Array:
    R = f * NA / n  # pupil radius
    return grid / R


def l2_sq_norm(a: Array, axis: Union[int, Tuple[int, ...]] = 0) -> Array:
    """Sum of squares, i.e. `x**2 + y**2`."""
    return jnp.sum(a**2, axis=axis)


def l2_norm(a: Array, axis: Union[int, Tuple[int, ...]] = 0) -> Array:
    """Square root of ``l2_sq_norm``, i.e. `sqrt(x**2 + y**2)`."""
    return jnp.sqrt(jnp.sum(a**2, axis=axis))


def l1_norm(a: Array, axis: Union[int, Tuple[int, ...]] = 0) -> Array:
    """Sum absolute value, i.e. `|x| + |y|`."""
    return jnp.sum(jnp.abs(a), axis=axis)


def linf_norm(a: Array, axis: Union[int, Tuple[int, ...]] = 0) -> Array:
    """Max absolute value, i.e. `max(|x|, |y|)`."""
    return jnp.max(jnp.abs(a), axis=axis)
