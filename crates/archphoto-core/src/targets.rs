//! Target classes: artifact (유물), feature (유구), site (유적).
//!
//! Ported from `archphoto.archaeo.targets`. Each class drives different
//! capture, processing, and deliverable expectations.

use crate::ContractResult;

/// Archaeological target scale/category.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TargetClass {
    /// 유물: small object, interior/exterior, flip capture.
    Artifact,
    /// 유구: floor, stone wall, section face, stratigraphic surface.
    Feature,
    /// 유적: survey area, multiple features, surrounding surface.
    Site,
}

impl TargetClass {
    pub fn label(self) -> &'static str {
        match self {
            Self::Artifact => "artifact",
            Self::Feature => "feature",
            Self::Site => "site",
        }
    }

    pub fn ko_label(self) -> &'static str {
        match self {
            Self::Artifact => "유물",
            Self::Feature => "유구",
            Self::Site => "유적",
        }
    }
}

/// What is being reconstructed and the expected deliverables.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct TargetSpec {
    pub target_class: TargetClass,
    pub identifier: String,
    pub deliverables: Vec<String>,
    pub notes: String,
}

impl TargetSpec {
    pub fn new(
        target_class: TargetClass,
        identifier: impl Into<String>,
        deliverables: Vec<String>,
        notes: impl Into<String>,
    ) -> ContractResult<Self> {
        let identifier = identifier.into();
        if identifier.trim().is_empty() {
            return Err("TargetSpec.identifier must be set".into());
        }
        Ok(Self {
            target_class,
            identifier,
            deliverables,
            notes: notes.into(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn target_spec_requires_non_empty_identifier() {
        assert!(TargetSpec::new(TargetClass::Artifact, "  ", vec![], "").is_err());
        let spec = TargetSpec::new(
            TargetClass::Feature,
            "TR-01",
            vec!["mesh".into(), "section".into()],
            "석렬 유구",
        )
        .unwrap();
        assert_eq!(spec.target_class.ko_label(), "유구");
        assert_eq!(spec.deliverables.len(), 2);
    }
}
