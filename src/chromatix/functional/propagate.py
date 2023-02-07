import jax.numpy as jnp
from ..field import Field
from einops import rearrange
from ..utils import center_pad, center_crop
from ..ops.fft import fftshift, fft, ifft
from typing import Optional

__all__ = ["propagate", "transform_propagate", "transfer_propagate", "exact_propagate"]


def transform_propagate(
    field: Field, z: float, n: float, *, N_pad: int, loop_axis: Optional[int] = None
) -> Field:
    """
    Fresnel propagate a field for a distance z using the transform method.

    Args:
      field: A LightField describing what should be propagated.
      z: A float that defines the distance to propagate.
      n: A float that defines the refractive index of the medium.
      N_pad: A keyword argument integer defining the pad length for the
      propagation FFT

    Returns:
      The propagated LightField.
    """

    # Fourier normalization factor
    # assert N_pad % 2 == 0, "Padding should be even."
    L = jnp.sqrt(field.spectrum * z / n)  # lengthscale L
    norm = (field.dx / L) ** 2

    # Calculating input phase change
    input_phase = jnp.pi * field.l2_sq_grid / L**2

    # Calculating new scaled output coordinates
    du = L**2 / ((field.shape[1] + N_pad) * field.dx)

    # Calculating output phase
    output_grid = field.l2_sq_grid * (du / field.dx) ** 2
    output_phase = jnp.pi * output_grid / L**2

    # Determining new field
    u = field.u * jnp.exp(1j * input_phase)
    u = center_pad(u, [0, int(N_pad / 2), int(N_pad / 2), 0])
    u = fftshift(fft(u, loop_axis))
    u = center_crop(u, [0, int(N_pad / 2), int(N_pad / 2), 0])

    # Final normalization and phase
    u *= norm * jnp.exp(1j * output_phase)

    return field.replace(u=u, dx=du)


def transfer_propagate(
    field: Field,
    z: float,
    n: float,
    *,
    N_pad: int,
    loop_axis: Optional[int] = None,
    mode: str = "full",
) -> Field:
    """
    Fresnel propagate a field for a distance z using the transfer method.

    Args:
      field: A LightField describing what should be propagated.
      z: A float that defines the distance to propagate.
      n: A float that defines the refractive index of the medium.
      N_pad: A keyword argument integer defining the pad length for the
      propagation FFT (NOTE: should not be a Jax array, otherwise a
      ConcretizationError will arise when traced!).

    Returns:
      The propagated LightField.
    """

    # assert N_pad % 2 == 0, "Padding should be even."
    # Calculating propagator
    L = jnp.sqrt(field.spectrum * z / n)  # lengthscale L
    f = jnp.fft.fftfreq(field.shape[1] + N_pad, d=field.dx.squeeze())
    fx, fy = rearrange(f, "h -> 1 h 1 1"), rearrange(f, "w -> 1 1 w 1")
    phase = -jnp.pi * L**2 * (fx**2 + fy**2)

    # Propagating field
    u = center_pad(field.u, [0, int(N_pad / 2), int(N_pad / 2), 0])
    u = ifft(fft(u, loop_axis) * jnp.exp(1j * phase), loop_axis)

    # Cropping output field
    match mode:
        case "full":
            field = field.replace(u=u)
        case "same":
            u = center_crop(u, [0, int(N_pad / 2), int(N_pad / 2), 0])
            field = field.replace(u=u)
        case other:
            raise NotImplementedError('Only "full" and "same" are supported.')

    return field


# Exact transfer method


def exact_propagate(
    field: Field,
    z: float,
    n: float,
    *,
    N_pad: int,
    loop_axis: Optional[int] = None,
    mode: str = "full",
) -> Field:
    """
    Exactly propagate a field for a distance z using the exact transfer method.

    Args:
      field: A LightField describing what should be propagated.
      z: A float that defines the distance to propagate.
      n: A float that defines the refractive index of the medium.
      N_pad: A keyword argument integer defining the pad length for the
      propagation FFT (NOTE: should not be a Jax array, otherwise a
      ConcretizationError will arise when traced!).

    Returns:
      The propagated LightField.
    """
    # Calculating propagator
    f = jnp.fft.fftfreq(field.shape[1] + N_pad, d=field.dx.squeeze())
    fx, fy = rearrange(f, "h -> 1 h 1 1"), rearrange(f, "w -> 1 1 w 1")
    kernel = 1 - (field.spectrum / n) ** 2 * (fx**2 + fy**2)
    kernel = jnp.maximum(kernel, 0.0)  # removing evanescent waves
    phase = 2 * jnp.pi * (z * n / field.spectrum) * jnp.sqrt(kernel)

    # Propagating field
    u = center_pad(field.u, [0, int(N_pad / 2), int(N_pad / 2), 0])
    u = ifft(fft(u, loop_axis) * jnp.exp(1j * phase), loop_axis)

    # Cropping output field
    match mode:
        case "full":
            field = field.replace(u=u)
        case "same":
            u = center_crop(u, [0, int(N_pad / 2), int(N_pad / 2), 0])
            field = field.replace(u=u)
        case other:
            raise NotImplementedError('Only "full" and "same" are supported.')

    return field


def propagate(
    field: Field,
    z: float,
    n: float,
    *,
    method: str = "transfer",
    mode: str = "full",
    N_pad: Optional[int] = None,
    loop_axis: Optional[int] = None,
) -> Field:
    # Only works for square fields?
    D = field.u.shape[1] * field.dx  # height of field in real coordinates
    Nf = jnp.max((D / 2) ** 2 / (field.spectrum * z))  # Fresnel number
    M = field.u.shape[1]  # height of field in pixels
    # TODO(dd): we should figure out a better approximation method, perhaps by
    # running a quick simulation and checking the aliasing level
    Q = 2 * jnp.maximum(1.0, M / (4 * Nf))  # minimum pad ratio * 2

    match method:
        case "transform":
            if N_pad is None:
                N = int(jnp.ceil((Q * M) / 2) * 2)
                N_pad = int((N - M))
            field = transform_propagate(field, z, n, N_pad=N_pad, loop_axis=loop_axis)
        case "transfer":
            if N_pad is None:
                N = int(jnp.ceil((Q * M) / 2) * 2)
                N_pad = int((N - M))
            field = transfer_propagate(
                field, z, n, N_pad=N_pad, loop_axis=loop_axis, mode=mode
            )
        case "exact":
            if N_pad is None:
                scale = jnp.max((field.spectrum / (2 * field.dx)))
                assert scale < 1, "Can't do exact transfer when dx < lambda / 2"
                Q = Q / jnp.sqrt(1 - scale**2)  # minimum pad ratio for exact transfer
                N = int(jnp.ceil((Q * M) / 2) * 2)
                N_pad = int((N - M))
            field = exact_propagate(
                field, z, n, N_pad=N_pad, loop_axis=loop_axis, mode=mode
            )

        case other:
            raise NotImplementedError(
                "Method must be one of 'transform', 'transfer', or 'exact'."
            )
    return field