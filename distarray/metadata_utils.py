# encoding: utf-8
# ---------------------------------------------------------------------------
#  Copyright (C) 2008-2014, IPython Development Team and Enthought, Inc.
#  Distributed under the terms of the BSD License.  See COPYING.rst.
# ---------------------------------------------------------------------------

import operator
from itertools import product
from functools import reduce
from collections import Sequence, Mapping

import numpy

from distarray import utils
from distarray.externals.six import next
from distarray.externals.six.moves import map


class InvalidGridShapeError(Exception):
    pass


class GridShapeError(Exception):
    pass


def check_grid_shape_preconditions(shape, dist, comm_size):
    """
    Verify various distarray parameters are correct before making a grid_shape.
    """
    if comm_size < 1:
        raise ValueError("comm_size >= 1 not satisfied, comm_size = %s" %
                         (comm_size,))
    if len(shape) != len(dist):
        raise ValueError("len(shape) == len(dist) not satisfied, len(shape) ="
                         " %s and len(dist) = %s" % (len(shape), len(dist)))
    if any(i < 0 for i in shape):
        raise ValueError("shape must be a sequence of non-negative integers, "
                         "shape = %s" % (shape,))
    if any(i not in ('b', 'c', 'n', 'u') for i in dist):
        raise ValueError("dist must be a sequence of 'b', 'n', 'c', 'u' "
                         "strings, dist = %s" % (dist,))


def check_grid_shape_postconditions(grid_shape, shape, dist, comm_size):
    if not (len(grid_shape) == len(shape) == len(dist)):
        raise ValueError("len(gird_shape) == len(shape) == len(dist) not "
                         "satisfied, len(grid_shape) = %s and len(shape) = %s "
                         "and len(dist) = %s" % (len(grid_shape), len(shape),
                                                 len(dist)))
    if any(gs < 1 for gs in grid_shape):
        raise ValueError("all(gs >= 1 for gs in grid_shape) not satisfied, "
                         "grid_shape = %s" % (grid_shape,))
    if any(gs != 1 for (d, gs) in zip(dist, grid_shape) if d == 'n'):
        raise ValueError("all(gs == 1 for (d, gs) in zip(dist, grid_shape) if "
                         "d == 'n', not satified dist = %s and grid_shape = "
                         "%s" % (dist, grid_shape))
    if any(gs > s for (s, gs) in zip(shape, grid_shape) if s > 0):
        raise ValueError("all(gs <= s for (s, gs) in zip(shape, grid_shape) "
                         "if s > 0) not satisfied, shape = %s and grid_shape "
                         "= %s" % (shape, grid_shape))
    if reduce(operator.mul, grid_shape, 1) > comm_size:
        raise ValueError("reduce(operator.mul, grid_shape, 1) <= comm_size not"
                         " satisfied, grid_shape = %s product = %s and "
                         "comm_size = %s" % (
                             grid_shape,
                             reduce(operator.mul, grid_shape, 1),
                             comm_size))


def normalize_grid_shape(grid_shape, shape, dist, comm_size):
    """Adds 1s to grid_shape so it has `ndims` dimensions.  Validates
    `grid_shape` tuple against the `dist` tuple and `comm_size`.
    """
    def check_normalization_preconditions(grid_shape, dist):
        if any(i < 0 for i in grid_shape):
            raise ValueError("grid_shape must be a sequence of non-negative "
                             "integers, grid_shape = %s" % (grid_shape,))
        if len(grid_shape) > len(dist):
            raise ValueError("len(grid_shape) <= len(dist) not satisfied, "
                             "len(grid_shape) = %s and len(dist) = %s" %
                             (len(grid_shape), len(dist)))
    check_grid_shape_preconditions(shape, dist, comm_size)
    check_normalization_preconditions(grid_shape, dist)

    ndims = len(shape)
    grid_shape = tuple(grid_shape) + (1,) * (ndims - len(grid_shape))

    if len(grid_shape) != len(dist):
        msg = "grid_shape's length (%d) not equal to dist's length (%d)"
        raise InvalidGridShapeError(msg % (len(grid_shape), len(dist)))
    if reduce(operator.mul, grid_shape, 1) > comm_size:
        msg = "grid shape %r not compatible with comm size of %d."
        raise InvalidGridShapeError(msg % (grid_shape, comm_size))
    return grid_shape


def make_grid_shape(shape, dist, comm_size):
    """ Generate a `grid_shape` from `shape` tuple and `dist` tuple.

    Does not assume that `dim_data` has `proc_grid_size` set for each
    dimension.

    Attempts to allocate processes optimally for distributed dimensions.

    Parameters
    ----------
    shape : tuple of int
        The global shape of the array.
    dist: tuple of str
        dist_type character per dimension.
    comm_size : int
        Total number of processes to distribute.

    Returns
    -------
    dist_grid_shape : tuple of int

    Raises
    ------
    GridShapeError
        if not possible to distribute `comm_size` processes over number of
        dimensions.
    """
    check_grid_shape_preconditions(shape, dist, comm_size)
    distdims = tuple(i for (i, v) in enumerate(dist) if v != 'n')
    ndistdim = len(distdims)

    if ndistdim == 0:
        dist_grid_shape = ()

    elif ndistdim == 1:
        # Trivial case: all processes used for the one distributed dimension.
        if comm_size >= shape[distdims[0]]:
            dist_grid_shape = (shape[distdims[0]],)
        else:
            dist_grid_shape = (comm_size,)

    elif comm_size == 1:
        # Trivial case: only one process to distribute over!
        dist_grid_shape = (1,) * ndistdim

    else:  # Main case: comm_size > 1, ndistdim > 1.
        factors = utils.mult_partitions(comm_size, ndistdim)
        if not factors:  # Can't factorize appropriately.
            raise GridShapeError("Cannot distribute array over processors.")

        reduced_shape = [shape[i] for i in distdims]

        # Reorder factors so they match the relative ordering in reduced_shape
        factors = [utils.mirror_sort(f, reduced_shape) for f in factors]

        # Pick the "best" factoring from `factors` according to which matches
        # the ratios among the dimensions in `shape`.
        rs_ratio = _compute_grid_ratios(reduced_shape)
        f_ratios = [_compute_grid_ratios(f) for f in factors]
        distances = [rs_ratio-f_ratio for f_ratio in f_ratios]
        norms = numpy.array([numpy.linalg.norm(d, 2) for d in distances])
        index = norms.argmin()
        # we now have the grid shape for the distributed dimensions.
        dist_grid_shape = tuple(int(i) for i in factors[index])

    # Create the grid_shape, all 1's for now.
    grid_shape = [1] * len(shape)

    # Fill grid_shape in the distdim slots using dist_grid_shape
    it = iter(dist_grid_shape)
    for distdim in distdims:
        grid_shape[distdim] = next(it)

    out_grid_shape = tuple(grid_shape)
    check_grid_shape_postconditions(out_grid_shape, shape, dist, comm_size)
    return out_grid_shape


def _compute_grid_ratios(shape):
    shape = tuple(map(float, shape))
    n = len(shape)
    ratios = []
    for (i, j) in product(range(n), range(n)):
        if i < j:
            ratios.append(shape[i] / shape[j])
    return numpy.array(ratios)


def normalize_dist(dist, ndim):
    """Return a tuple containing dist-type for each dimension.

    Parameters
    ----------
    dist : str, list, tuple, or dict
    ndim : int

    Returns
    -------
    tuple of str
        Contains string distribution type for each dim.

    Examples
    --------
    >>> normalize_dist({0: 'b', 3: 'c'}, 4)
    ('b', 'n', 'n', 'c')
    """
    if isinstance(dist, Sequence):
        return tuple(dist) + ('n',) * (ndim - len(dist))
    elif isinstance(dist, Mapping):
        return tuple(dist.get(i, 'n') for i in range(ndim))
    else:
        raise TypeError("Dist must be a string, tuple, list or dict")


def _start_stop_block(size, proc_grid_size, proc_grid_rank):
    """Return `start` and `stop` for a regularly distributed block dim."""
    nelements = size // proc_grid_size
    if size % proc_grid_size != 0:
        nelements += 1

    start = proc_grid_rank * nelements
    if start > size:
        start = size

    stop = start + nelements
    if stop > size:
        stop = size

    return start, stop


def distribute_block_indices(dd):
    """Fill in `start` and `stop` in dim dict `dd`."""
    if ('start' in dd) and ('stop' in dd):
        return
    else:
        dd['start'], dd['stop'] = _start_stop_block(dd['size'],
                                                    dd['proc_grid_size'],
                                                    dd['proc_grid_rank'])


def distribute_cyclic_indices(dd):
    """Fill in `start` in dim dict `dd`."""
    if 'start' in dd:
        return
    else:
        dd['start'] = dd['proc_grid_rank']


def distribute_indices(dd):
    """Fill in index related keys in dim dict `dd`."""
    dist_type = dd['dist_type']
    try:
        {'n': lambda dd: None,
         'b': distribute_block_indices,
         'c': distribute_cyclic_indices}[dist_type](dd)
    except KeyError:
        msg = "dist_type %r not supported."
        raise TypeError(msg % dist_type)


def normalize_dim_dict(dd):
    """Fill out some degenerate dim_dicts."""

    # TODO: Fill out empty dim_dict alias here?

    if dd['dist_type'] == 'n':
        dd['proc_grid_size'] = 1
        dd['proc_grid_rank'] = 0


def positivify(index, size):
    if 0 <= index < size:
        return index
    elif -size <= index < 0:
        return size + index
    else:
        raise IndexError("Index %s out of bounds" % index)


def normalize_reduction_axes(axes, ndim):
    if axes is None:
        axes = tuple(range(ndim))
    elif not isinstance(axes, Sequence):
        axes = (positivify(axes, ndim),)
    else:
        axes = tuple(positivify(a, ndim) for a in axes)
    return axes
