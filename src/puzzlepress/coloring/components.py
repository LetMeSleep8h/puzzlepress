"""Connected ink regions of a grayscale image, by run-length labeling, with a bound.

Pixels at or below `level` are ink. Each row is split into ink runs (a C-speed
regular expression over the row's mask), and runs that touch a run in the row
above, diagonals included, are joined with union-find. So regions are 8-connected:
a diagonal one-pixel line is one stroke. Work grows with the number of runs, not
pixels. `max_ink` bounds it; exceeding it raises, never a partial answer.

A small region is *isolated* when no other ink lies within `radius` pixels of its
bounding box: a speck of dust, not a piece of a faint or dashed line. Despeckling
removes isolated regions only, so it cannot erase fragments of line work.
"""

import re
from dataclasses import dataclass

from PIL import Image

_RUN = re.compile(rb"\xff+")


class TooMuchInk(Exception):
    """More ink pixels than the bound allows; nothing was measured."""


def ink_mask(gray: Image.Image, level: int) -> bytes:
    """255 for ink pixels (at or below `level`), 0 for paper."""
    return gray.point(lambda v: 255 if v <= level else 0).tobytes()


@dataclass(frozen=True)
class Region:
    area: int
    runs: tuple[tuple[int, int, int], ...]  # (row, start, end) with `end` exclusive.

    @property
    def box(self) -> tuple[int, int, int, int]:
        """left, top, right, bottom (exclusive)."""
        rows = [run[0] for run in self.runs]
        return (
            min(run[1] for run in self.runs),
            min(rows),
            max(run[2] for run in self.runs),
            max(rows) + 1,
        )


@dataclass(frozen=True)
class Labeling:
    width: int
    height: int
    mask: bytes
    areas: tuple[int, ...]
    small: tuple[Region, ...]  # Regions of at most `keep_up_to` pixels, with their runs.

    def isolated(self, region: Region, radius: int) -> bool:
        left, top, right, bottom = region.box
        left, top = max(0, left - radius), max(0, top - radius)
        right, bottom = min(self.width, right + radius), min(self.height, bottom + radius)
        ink = 0
        for row in range(top, bottom):
            start = row * self.width
            ink += self.mask.count(255, start + left, start + right)
        return ink == region.area


def label(gray: Image.Image, level: int, max_ink: int, keep_up_to: int = 0) -> Labeling:
    width, height = gray.size
    mask = ink_mask(gray, level)
    ink = mask.count(255)
    if ink > max_ink:
        raise TooMuchInk(f"{ink:,} ink pixels; at most {max_ink:,} can be analyzed")
    parent: list[int] = []
    runs: list[tuple[int, int, int]] = []

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    previous: list[int] = []  # Run indices of the row above, in start order.
    for row in range(height):
        offset = row * width
        current: list[int] = []
        pointer = 0
        for match in _RUN.finditer(mask, offset, offset + width):
            start, end = match.start() - offset, match.end() - offset
            index = len(runs)
            runs.append((row, start, end))
            parent.append(index)
            current.append(index)
            # Runs above that touch [start - 1, end] (8-connectivity).
            while pointer < len(previous) and runs[previous[pointer]][2] < start:
                pointer += 1
            probe = pointer
            while probe < len(previous) and runs[previous[probe]][1] <= end:
                a, b = find(index), find(previous[probe])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                probe += 1
        previous = current
    totals: dict[int, int] = {}
    members: dict[int, list[tuple[int, int, int]]] = {}
    for index, run in enumerate(runs):
        root = find(index)
        totals[root] = totals.get(root, 0) + run[2] - run[1]
        if keep_up_to:
            members.setdefault(root, []).append(run)
    small = tuple(
        Region(totals[root], tuple(members[root]))
        for root in sorted(totals)
        if keep_up_to and totals[root] <= keep_up_to
    )
    return Labeling(width, height, mask, tuple(totals[root] for root in sorted(totals)), small)


def region_areas(gray: Image.Image, level: int, max_ink: int) -> tuple[int, ...]:
    """Pixel count of every 8-connected ink region, in scan order."""
    return label(gray, level, max_ink).areas


def isolated_specks(
    gray: Image.Image, level: int, max_area: int, radius: int, max_ink: int
) -> tuple[Region, ...]:
    """Regions of at most `max_area` pixels with no other ink within `radius` pixels."""
    labeling = label(gray, level, max_ink, keep_up_to=max_area)
    return tuple(region for region in labeling.small if labeling.isolated(region, radius))


def paint_white(gray: Image.Image, regions: tuple[Region, ...]) -> Image.Image:
    pixels = bytearray(gray.tobytes())
    width = gray.width
    for region in regions:
        for row, start, end in region.runs:
            pixels[row * width + start : row * width + end] = b"\xff" * (end - start)
    return Image.frombytes("L", gray.size, bytes(pixels))


def remove_isolated(
    gray: Image.Image, level: int, max_area: int, radius: int, max_ink: int
) -> tuple[Image.Image, int]:
    """Paint isolated ink regions of at most `max_area` pixels white."""
    if max_area <= 0:
        return gray.copy(), 0
    specks = isolated_specks(gray, level, max_area, radius, max_ink)
    return (paint_white(gray, specks), len(specks)) if specks else (gray.copy(), 0)
