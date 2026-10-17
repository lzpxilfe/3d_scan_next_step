"""archphoto — open-source archaeology-specific photogrammetry.

Working package name (provisional [O]). Produces verifiable 3D meshes from
photographs and survey control for artifacts, features, and sites.

Sub-packages:
    project   project/session management and raw-data preservation
    sensing   photo / camera / GCP / checkpoint input
    geom      coordinate reference systems, units, transforms
    recon     reconstruction pipeline (new algorithm + fast reconstruction R01)
    engines   adapters to existing photogrammetry engines (baseline path)
    archaeo   archaeology-specific workflow
    mesh      3D mesh construction and export
    quality   independent validation (checkpoints excluded from calibration)
    runlog    run records, resource usage, processing vs. survey-validation state
    gui       user interface (framework undecided, stub)

Nothing in this package fabricates survey accuracy. See README.md and
docs/DECISIONS.md.
"""

__version__ = "0.0.1"

__all__ = ["__version__"]
