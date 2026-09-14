"""A QR encoder, because the alternative was a dependency to draw a square.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Pairing shows a QR in a terminal. That is the entire requirement, and it is not
worth a package: byte mode, error correction level M, versions 1 to 10, which
covers every URL this will ever hold and nothing else. Anything longer than
about two hundred characters raises rather than silently producing a code that
a phone cannot read.

The encoder is written against ISO/IEC 18004 and checked against an
independent implementation in the tests — matrix for matrix, not "it looks like
a QR code". That check is the only reason to trust hand-written Reed-Solomon.

Level M rather than L: a terminal repaints, a phone camera is held by a human
hand, and the eleven extra codewords buy roughly fifteen percent recovery for a
payload that has plenty of room to spare.
"""

from __future__ import annotations

#: Per version (1-10) at error correction level M: error codewords per block,
#: then the blocks themselves as (count, data codewords per block).
#:
#: Straight from the standard's table 9. It is transcription, so the tests
#: check the arithmetic holds — total codewords must equal the module capacity.
_SPEC: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    1:  (10, ((1, 16),)),
    2:  (16, ((1, 28),)),
    3:  (26, ((1, 44),)),
    4:  (18, ((2, 32),)),
    5:  (24, ((2, 43),)),
    6:  (16, ((4, 27),)),
    7:  (18, ((4, 31),)),
    8:  (22, ((2, 38), (2, 39))),
    9:  (22, ((3, 36), (2, 37))),
    10: (26, ((4, 43), (1, 44))),
}

#: Row and column centres of the alignment patterns, per version.
_ALIGN: dict[int, tuple[int, ...]] = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}

_BYTE_MODE = 0b0100
_LEVEL_M = 0b00

# The eight mask patterns, indexed by the number written into the format bits.
_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


# ------------------------------------------------------------------ GF(256)
#
# The field the standard specifies: x^8 + x^4 + x^3 + x^2 + 1. Log tables
# built once at import, because every block's error correction walks them.

_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_build_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list[int]:
    """The generator polynomial for `degree` error codewords."""
    poly = [1]
    for i in range(degree):
        # Multiply by (x - alpha^i); subtraction is XOR here.
        nxt = [0] * (len(poly) + 1)
        for j, coefficient in enumerate(poly):
            nxt[j] ^= coefficient
            nxt[j + 1] ^= _mul(coefficient, _EXP[i])
        poly = nxt
    return poly


def error_codewords(data: bytes, count: int) -> list[int]:
    """Reed-Solomon remainder: `count` error correction codewords for `data`."""
    gen = _generator(count)
    remainder = list(data) + [0] * count
    for i in range(len(data)):
        lead = remainder[i]
        if lead == 0:
            continue
        for j, coefficient in enumerate(gen):
            remainder[i + j] ^= _mul(coefficient, lead)
    return remainder[len(data):]


# ------------------------------------------------------------------ encoding

def _capacity(version: int) -> int:
    """Data codewords available at level M."""
    _, blocks = _SPEC[version]
    return sum(count * size for count, size in blocks)


def _version_for(length: int) -> int:
    """Smallest version that holds `length` bytes, header included."""
    for version in sorted(_SPEC):
        header = 4 + (8 if version < 10 else 16)
        if (header + length * 8 + 7) // 8 <= _capacity(version):
            return version
    raise ValueError(
        f"{length} bytes is more than a version 10 QR code holds. "
        "This encoder is for pairing URLs, not arbitrary payloads.")


def _bitstream(payload: bytes, version: int) -> bytes:
    """Mode, length, data, terminator, padding — as whole codewords."""
    bits: list[int] = []

    def push(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    push(_BYTE_MODE, 4)
    push(len(payload), 8 if version < 10 else 16)
    for byte in payload:
        push(byte, 8)

    capacity = _capacity(version) * 8
    push(0, min(4, capacity - len(bits)))          # terminator, truncated to fit
    bits.extend([0] * (-len(bits) % 8))            # to a codeword boundary

    out = bytearray(
        int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8))
    # The standard's pad bytes, alternating, until the version is full.
    pad = (0xEC, 0x11)
    while len(out) < _capacity(version):
        out.append(pad[len(out) % 2])
    return bytes(out)


def _interleave(data: bytes, version: int) -> list[int]:
    """Split into blocks, add error correction, and interleave both."""
    ec_per_block, groups = _SPEC[version]

    blocks: list[bytes] = []
    at = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[at:at + size])
            at += size

    ec = [error_codewords(block, ec_per_block) for block in blocks]

    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        out.extend(block[i] for block in blocks if i < len(block))
    for i in range(ec_per_block):
        out.extend(block[i] for block in ec)
    return out


# ------------------------------------------------------------------ the grid

def _reserve(size: int, version: int) -> tuple[list[list[int]], list[list[bool]]]:
    """The function patterns, and a map of what data may not overwrite."""
    grid = [[0] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def finder(top: int, left: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = top + r, left + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                ring = max(abs(r - 3), abs(c - 3))
                grid[rr][cc] = 1 if ring in (0, 1, 3) and 0 <= r < 7 and 0 <= c < 7 else 0
                fixed[rr][cc] = True

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(size):                                   # timing patterns
        if not fixed[6][i]:
            grid[6][i] = 1 - i % 2
            fixed[6][i] = True
        if not fixed[i][6]:
            grid[i][6] = 1 - i % 2
            fixed[i][6] = True

    centres = _ALIGN[version]
    # Only the three that would sit on a finder are omitted. The ones that land
    # on the timing pattern — every version from 7 up has them — are drawn, and
    # skipping those is why a version 7 code scans as nothing at all.
    corners = ({(centres[0], centres[0]), (centres[0], centres[-1]),
                (centres[-1], centres[0])} if centres else set())
    for r in centres:
        for c in centres:
            if (r, c) in corners:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    grid[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
                    fixed[r + dr][c + dc] = True

    for i in range(9):                                      # format information
        fixed[8][i] = True
        fixed[i][8] = True
    for i in range(8):                                      # and its second copy
        fixed[8][size - 1 - i] = True
        fixed[size - 1 - i][8] = True
    grid[size - 8][8] = 1                                   # the always-dark module

    if version >= 7:
        for i in range(18):
            r, c = i // 3, i % 3
            fixed[size - 11 + c][r] = True
            fixed[r][size - 11 + c] = True

    return grid, fixed


def _place(grid: list[list[int]], fixed: list[list[bool]], codewords: list[int]) -> None:
    """The zigzag: upward and downward two-module columns from the right."""
    size = len(grid)
    bits = [(word >> shift) & 1 for word in codewords for shift in range(7, -1, -1)]
    at = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:            # the vertical timing pattern is not a column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if fixed[row][c]:
                    continue
                grid[row][c] = bits[at] if at < len(bits) else 0
                at += 1
        upward = not upward
        col -= 2


def _bch(value: int, generator: int, width: int) -> int:
    """Remainder of `value` shifted into `width` check bits."""
    remainder = value << width
    top = generator.bit_length() - 1
    while remainder.bit_length() - 1 >= top:
        remainder ^= generator << (remainder.bit_length() - 1 - top)
    return remainder


def _write_format(grid: list[list[int]], mask: int) -> None:
    size = len(grid)
    raw = (_LEVEL_M << 3) | mask
    bits = ((raw << 10) | _bch(raw, 0b10100110111, 10)) ^ 0b101010000010010

    # Most significant bit first: (8, 0) carries bit 14, not bit 0. Reversed,
    # the code still scans — as a different error correction level, against the
    # wrong mask — which is the kind of wrong that looks fine until it isn't.
    def bit(i: int) -> int:
        return (bits >> (14 - i)) & 1

    # Both copies, bit by bit. Written out rather than looped cleverly because
    # the two copies split at different bits (8 and 6) and every wrong guess
    # here produces a code that scans as a different error correction level.
    for i in range(15):
        b = bit(i)
        if i < 6:
            grid[8][i] = b
        elif i == 6:
            grid[8][7] = b
        elif i == 7:
            grid[8][8] = b
        elif i == 8:
            grid[7][8] = b
        else:
            grid[14 - i][8] = b

        if i < 7:
            grid[size - 1 - i][8] = b
        else:
            grid[8][size - 15 + i] = b


def _write_version(grid: list[list[int]], version: int) -> None:
    if version < 7:
        return
    size = len(grid)
    bits = (version << 12) | _bch(version, 0b1111100100101, 12)
    for i in range(18):
        b = (bits >> i) & 1
        grid[size - 11 + i % 3][i // 3] = b
        grid[i // 3][size - 11 + i % 3] = b


def _finder_like(line: list[int], size: int) -> int:
    """Rule three: 1:1:3:1:1 occurrences that could be mistaken for a finder.

    The standard asks for four light modules before or after the pattern, and
    the quiet zone counts — a pattern flush against the edge of the symbol
    qualifies with nothing beside it at all. Overlapping matches are not scored
    twice; after a hit the scan resumes past the pattern, and after a near-miss
    it resumes inside it, since the next possible start is four modules along.
    """
    pattern = [1, 0, 1, 1, 1, 0, 1]
    score = 0
    at = 0
    while at <= size - 7:
        if line[at:at + 7] != pattern:
            at += 1
            continue
        if (at == 0 or at == size - 7
                or not any(line[max(at - 4, 0):at])
                or not any(line[at + 7:at + 11])):
            score += 40
            at += 7
        else:
            at += 4
    return score


def _penalty(grid: list[list[int]]) -> int:
    """The standard's four mask penalties. Lower is a better mask."""
    size = len(grid)
    score = 0

    for line in (grid, [list(col) for col in zip(*grid, strict=True)]):
        for row in line:
            run, previous = 1, row[0]
            for module in row[1:]:
                if module == previous:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, previous = 1, module
            if run >= 5:
                score += run - 2

    for r in range(size - 1):                               # 2x2 blocks
        for c in range(size - 1):
            quad = grid[r][c] + grid[r][c + 1] + grid[r + 1][c] + grid[r + 1][c + 1]
            if quad in (0, 4):
                score += 3

    for line in (grid, [list(col) for col in zip(*grid, strict=True)]):
        for row in line:
            score += _finder_like(row, size)

    dark = sum(sum(row) for row in grid)
    score += int(abs(dark * 100.0 / (size * size) - 50.0) // 5) * 10
    return score


def matrix(payload: str) -> list[list[int]]:
    """The QR modules for `payload`: 1 is dark, 0 is light, no quiet zone."""
    data = payload.encode("utf-8")
    version = _version_for(len(data))
    size = version * 4 + 17

    codewords = _interleave(_bitstream(data, version), version)
    base, fixed = _reserve(size, version)
    _place(base, fixed, codewords)
    _write_version(base, version)

    best, best_score = None, None
    for mask in range(8):
        candidate = [row[:] for row in base]
        rule = _MASKS[mask]
        for r in range(size):
            for c in range(size):
                if not fixed[r][c] and rule(r, c):
                    candidate[r][c] ^= 1
        _write_format(candidate, mask)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score

    assert best is not None
    return best


# ---------------------------------------------------------------- rendering

#: Four light modules on every side. Without it a camera cannot find the
#: code — this is the single most common reason a terminal QR will not scan.
QUIET = 4

_UPPER = "▀"


def terminal(payload: str, *, colour: bool = True) -> str:
    """A scannable QR for a normal terminal, two module rows per text row.

    Half-blocks because a terminal cell is about twice as tall as it is wide:
    one module per cell would give a code stretched to twice its height, which
    phones refuse. Foreground paints the upper module, background the lower.

    `colour=False` falls back to full blocks at two characters per module, for
    somewhere that strips ANSI. It is twice as wide and still scans.
    """
    grid = matrix(payload)
    size = len(grid)
    padded = [[0] * (size + QUIET * 2) for _ in range(QUIET)]
    for row in grid:
        padded.append([0] * QUIET + row + [0] * QUIET)
    padded.extend([0] * (size + QUIET * 2) for _ in range(QUIET))
    # An odd number of rows would leave the last one paired with nothing.
    if len(padded) % 2:
        padded.append([0] * len(padded[0]))

    if not colour:
        return "\n".join("".join("  " if m else "██" for m in row)
                         for row in padded)

    lines = []
    for i in range(0, len(padded), 2):
        top, bottom = padded[i], padded[i + 1]
        cells = []
        for t, b in zip(top, bottom, strict=True):
            # Dark module -> black, light module -> bright white. Explicit on
            # both layers, so a terminal with a light or dark theme is irrelevant.
            cells.append(f"\x1b[{30 if t else 97}m\x1b[{40 if b else 107}m{_UPPER}")
        lines.append("".join(cells) + "\x1b[0m")
    return "\n".join(lines)
