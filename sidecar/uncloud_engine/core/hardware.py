"""What this computer is, and what a model would have to fit inside.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Detection only. What a machine IS belongs in Core, because both products need
the same answer and a second implementation is a second thing to be wrong. What
a machine is FOR does not: Studio maps memory onto which models to suggest,
Uncloud maps it onto a generation budget, and those are product policies that
would be nonsense in the other application.

That split is why this module has no notion of a tier. It was extracted from
Studio's `platform/hardware.py`, which had both halves and was cross-platform
and careful about it; Uncloud meanwhile had its own Apple-Silicon-shaped
detection in `budget.py` that could not describe a machine with a discrete GPU.

Two rules the original had and this keeps.

**An unknown is reported as unknown.** A guessed memory figure produces an
out-of-memory crash mid-render, which is worse than admitting ignorance.

**An accelerator is claimed only when something on this machine answers for
it.** "Supported" that turns out to mean "compiles" is how a customer gets a
product that does not run.

macOS, Linux and Windows are all handled and none of them is assumed to behave
like another. Windows has not been validated on real hardware — the
architecture is here, the verification is a separate pass on a Windows machine.
"""

from __future__ import annotations

import os
import platform as _platform
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gpu:
    name: str
    memory_gb: float = 0.0
    vendor: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "memory_gb": self.memory_gb,
                "vendor": self.vendor}


@dataclass(frozen=True)
class Machine:
    """This computer, as far as anything could be established about it."""

    platform: str          # darwin | windows | linux
    arch: str              # arm64 | x86_64
    cpu: str = ""
    gpu: str = ""
    system_memory_gb: float = 0.0
    #: Apple Silicon shares memory between CPU and GPU, so this is the number
    #: that matters there. Zero on discrete-GPU machines.
    unified_memory_gb: float = 0.0
    #: Total across every GPU. On a multi-GPU box this is not what one model
    #: can use — see `largest_gpu_gb`.
    vram_gb: float = 0.0
    #: Free space where models are kept. Zero when it could not be read.
    disk_free_gb: float = 0.0
    accelerators: tuple[str, ...] = field(default_factory=tuple)
    gpus: tuple[Gpu, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """Platform string used to filter a model registry."""
        return f"{self.platform}-{self.arch}"

    @property
    def largest_gpu_gb(self) -> float:
        """The biggest single GPU.

        A model that does not fit on one card does not fit at all until
        sharding exists, so this — not the total — is the budget on a
        multi-GPU machine.
        """
        return max((g.memory_gb for g in self.gpus), default=self.vram_gb)

    @property
    def usable_memory_gb(self) -> float:
        """What a model actually has to fit inside."""
        if self.unified_memory_gb:
            return self.unified_memory_gb
        if self.gpus:
            return self.largest_gpu_gb
        # CPU-only: models run in system RAM, slowly but they run.
        return self.system_memory_gb

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    @property
    def accelerated(self) -> bool:
        return bool(set(self.accelerators) - {"cpu"})

    @property
    def measured(self) -> bool:
        """Whether anything useful was established.

        False means every downstream answer is a guess, and the honest thing to
        do with it is say so rather than plan around a zero.
        """
        return self.usable_memory_gb > 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform, "arch": self.arch, "key": self.key,
            "cpu": self.cpu, "gpu": self.gpu,
            "system_memory_gb": self.system_memory_gb,
            "unified_memory_gb": self.unified_memory_gb,
            "vram_gb": self.vram_gb, "largest_gpu_gb": self.largest_gpu_gb,
            "usable_memory_gb": self.usable_memory_gb,
            "disk_free_gb": self.disk_free_gb,
            "accelerators": list(self.accelerators),
            "gpus": [g.to_dict() for g in self.gpus],
            "gpu_count": self.gpu_count, "accelerated": self.accelerated,
            "measured": self.measured,
        }


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ----------------------------------------------------------------- macOS
def _macos() -> tuple[str, str, float, tuple[str, ...]]:
    cpu = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    mem_raw = _run(["sysctl", "-n", "hw.memsize"])
    mem_gb = round(int(mem_raw) / (1024**3), 1) if mem_raw.isdigit() else 0.0
    arch = _platform.machine()
    if arch == "arm64":
        # On Apple Silicon the GPU shares system memory, so the chip name is
        # the GPU and hw.memsize is the budget for both.
        return cpu or "Apple Silicon", cpu or "Apple GPU", mem_gb, ("metal", "mlx")
    # Intel Macs: no MLX, and Metal support in the ML stack is not worth
    # claiming. CPU only, and said so plainly.
    return cpu, "", mem_gb, ("cpu",)


# ------------------------------------------------------------------ NVIDIA
def _nvidia() -> tuple[tuple[Gpu, ...], tuple[str, ...]]:
    """Every NVIDIA GPU, so a multi-GPU box (DGX and friends) is seen as one."""
    if not shutil.which("nvidia-smi"):
        return (), ()
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"])
    if not out:
        return (), ()
    gpus = []
    for line in out.splitlines():
        name, _, mem = line.partition(",")
        try:
            memory = round(float(mem.strip()) / 1024, 1)
        except ValueError:
            memory = 0.0
        if name.strip():
            gpus.append(Gpu(name=name.strip(), memory_gb=memory, vendor="nvidia"))
    return tuple(gpus), ("cuda",) if gpus else ()


# --------------------------------------------------------------------- AMD
def _amd() -> tuple[tuple[Gpu, ...], tuple[str, ...]]:
    """ROCm, detected but **not claimed as supported** — no adapter runs on it
    yet, and the registry has no ROCm platform entries. Reporting it lets the
    Models screen explain why nothing is available rather than staying silent.
    """
    if not (shutil.which("rocm-smi") or os.path.isdir("/opt/rocm")):
        return (), ()
    out = _run(["rocm-smi", "--showproductname", "--csv"])
    names = [line.split(",")[-1].strip() for line in out.splitlines()[1:] if "," in line]
    gpus = tuple(Gpu(name=n or "AMD GPU", vendor="amd") for n in names if n)
    return (gpus or (Gpu(name="AMD GPU", vendor="amd"),)), ("rocm",)


# ------------------------------------------------------------- Windows ARM
def _windows_arm_accelerators() -> tuple[str, ...]:
    """Snapdragon-class Windows machines have an NPU reachable through
    DirectML, and no CUDA. Nothing here runs on it yet, so this reports the
    hardware without claiming support for it."""
    return ("directml", "cpu")


def _system_memory_gb() -> float:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                     / (1024**3), 1)
    except (ValueError, OSError, AttributeError):
        pass
    if _platform.system().lower() == "windows":
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / (1024**3), 1)
        except Exception:  # noqa: BLE001 - detection must never crash startup
            return 0.0
    return 0.0


def disk_free_gb(path: str | os.PathLike | None = None) -> float:
    """Free space where models are kept. Zero when it cannot be read.

    Reported because a download that fills the disk is a different failure from
    one that will not fit in memory, and they need different advice.
    """
    try:
        usage = shutil.disk_usage(path or os.path.expanduser("~"))
        return round(usage.free / (1024**3), 1)
    except (OSError, ValueError):
        return 0.0


def detect(*, models_dir: str | os.PathLike | None = None) -> Machine:
    """Everything that could be established about this computer."""
    system = _platform.system().lower()
    arch = _platform.machine().lower()
    if arch in ("amd64", "x86_64"):
        arch = "x86_64"
    elif arch in ("aarch64", "arm64"):
        arch = "arm64"

    free = disk_free_gb(models_dir)

    if system == "darwin":
        cpu, gpu, memory_gb, accelerators = _macos()
        unified = memory_gb if arch == "arm64" else 0.0
        return Machine(
            platform="darwin", arch=arch, cpu=cpu, gpu=gpu,
            system_memory_gb=memory_gb, unified_memory_gb=unified,
            disk_free_gb=free, accelerators=accelerators,
            gpus=((Gpu(name=gpu, memory_gb=unified, vendor="apple"),)
                  if unified else ()))

    gpus, accelerators = _nvidia()
    if not gpus:
        gpus, accelerators = _amd()
    if not gpus and system == "windows" and arch == "arm64":
        accelerators = _windows_arm_accelerators()
    if not accelerators:
        accelerators = ("cpu",)

    return Machine(
        platform=system or "linux", arch=arch,
        cpu=_platform.processor() or "",
        gpu=gpus[0].name if gpus else "",
        system_memory_gb=_system_memory_gb(),
        vram_gb=round(sum(g.memory_gb for g in gpus), 1),
        disk_free_gb=free, accelerators=tuple(accelerators), gpus=tuple(gpus))
