//! archphoto-core — survey data contracts for the archaeology
//! photogrammetry program.
//!
//! Ported from the Python reference (`src/archphoto/`, kept intact in git
//! history). Port order follows decision D-2026-10-12-11:
//! units/frame (`crs`) → sensing contracts (`sensing`) → quality layer
//! (`quality`) → geometry → registration → GUI shell.
//!
//! Honesty contracts are enforced structurally here wherever Python enforced
//! them at runtime: a frame without a CRS id is unrepresentable, an UNKNOWN
//! role cannot become a control point, and using a fitted point for
//! independent evaluation is refused.

pub mod baseline;
pub mod crs;
pub mod export;
pub mod measure;
pub mod mesh;
pub mod ortho;
pub mod plane;
pub mod preflight;
pub mod project;
pub mod quality;
pub mod register;
pub mod reproducibility;
pub mod runlog;
pub mod section;
pub mod sensing;
pub mod targets;
pub mod transform;

/// 3D point as (x, y, z) in an explicit frame's units.
pub type Point3D = [f64; 3];

/// Contract failures carry the refusal reason as a message. Until the error
/// taxonomy grows, messages mirror the Python reference so ported tests stay
/// comparable.
pub type ContractResult<T> = Result<T, String>;
