"""Training and customising models locally.

Free and local, deliberately. The basic ability to fine-tune a model you
already have on data you already own is not a feature to sell back to
somebody — it is what a local-first AI product is FOR. What could reasonably
become a paid tier is the automated half above it: dataset generation,
distillation, hyperparameter sweeps, multi-model judging. None of that is here
yet, and the split is recorded so the line stays where it was drawn rather
than migrating downwards.

Three modules, in the order a run uses them:

    datasets     read it, and refuse the ones that will not work
    feasibility  will it fit on this machine, and how long
    jobs         run it, report it, keep the adapter
"""

from . import datasets, feasibility, jobs

__all__ = ["datasets", "feasibility", "jobs"]
