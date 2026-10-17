//! Project and session manifest.
//!
//! Ported from `archphoto.project.manifest`.
//! PRINCIPLE (`AGENTS.md`): original photos and original survey data must never
//! be overwritten or auto-deleted. The manifest records integrity digests so
//! that a later run can detect if an original changed. All writes go to
//! derived/output areas, never back to the raw area.

use std::fs;
use std::path::{Path, PathBuf};

use crate::ContractResult;
use crate::sensing::sha256_file;

/// Classification of an immutable original file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RawKind {
    Photo,
    Survey,
    Other,
}

impl RawKind {
    pub fn label(self) -> &'static str {
        match self {
            Self::Photo => "photo",
            Self::Survey => "survey",
            Self::Other => "other",
        }
    }
}

/// One preserved original file (photo or survey export).
///
/// `sha256` is captured at ingest; [`ProjectManifest::verify_raw_integrity`]
/// later compares against it in read-only mode.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct RawItem {
    pub rel_path: String,
    pub sha256: String,
    pub kind: RawKind,
    pub byte_size: u64,
}

impl RawItem {
    pub fn new(
        rel_path: impl Into<String>,
        sha256: impl Into<String>,
        kind: RawKind,
        byte_size: u64,
    ) -> ContractResult<Self> {
        let rel_path = rel_path.into();
        let sha256 = sha256.into();
        if rel_path.trim().is_empty() {
            return Err("RawItem.rel_path must be set".into());
        }
        if sha256.trim().is_empty() {
            return Err("RawItem.sha256 must be set".into());
        }
        Ok(Self {
            rel_path,
            sha256,
            kind,
            byte_size,
        })
    }

    /// Inspect `path` in read-only mode and build a [`RawItem`].
    pub fn from_file(path: &Path, kind: RawKind) -> ContractResult<Self> {
        let meta = fs::metadata(path)
            .map_err(|e| format!("failed to read metadata of {}: {e}", path.display()))?;
        let digest = sha256_file(path)?;
        Self::new(
            path.to_string_lossy().into_owned(),
            digest,
            kind,
            meta.len(),
        )
    }
}

/// Top-level project record separating the immutable RAW area from DERIVED outputs.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct ProjectManifest {
    pub project_id: String,
    pub title: String,
    pub raw_root: Option<PathBuf>,
    pub output_root: Option<PathBuf>,
    pub raw_items: Vec<RawItem>,
    pub crs_id: Option<String>,
}

impl ProjectManifest {
    pub fn new(project_id: impl Into<String>, title: impl Into<String>) -> ContractResult<Self> {
        let project_id = project_id.into();
        if project_id.trim().is_empty() {
            return Err("ProjectManifest.project_id must be set".into());
        }
        Ok(Self {
            project_id,
            title: title.into(),
            raw_root: None,
            output_root: None,
            raw_items: Vec::new(),
            crs_id: None,
        })
    }

    #[must_use]
    pub fn with_raw_root(mut self, raw_root: impl Into<PathBuf>) -> Self {
        self.raw_root = Some(raw_root.into());
        self
    }

    #[must_use]
    pub fn with_output_root(mut self, output_root: impl Into<PathBuf>) -> Self {
        self.output_root = Some(output_root.into());
        self
    }

    #[must_use]
    pub fn with_crs_id(mut self, crs_id: impl Into<String>) -> Self {
        self.crs_id = Some(crs_id.into());
        self
    }

    pub fn register_raw(&mut self, item: RawItem) {
        self.raw_items.push(item);
    }

    /// Return `rel_path`s whose stored digest or byte size no longer matches disk.
    ///
    /// Recomputes SHA-256 in read-only mode without ever modifying originals.
    #[must_use]
    pub fn verify_raw_integrity(&self) -> Vec<String> {
        let mut mismatched = Vec::new();
        for item in &self.raw_items {
            let target = match &self.raw_root {
                Some(root) => root.join(&item.rel_path),
                None => PathBuf::from(&item.rel_path),
            };
            let Ok(meta) = fs::metadata(&target) else {
                mismatched.push(item.rel_path.clone());
                continue;
            };
            if !meta.is_file() || meta.len() != item.byte_size {
                mismatched.push(item.rel_path.clone());
                continue;
            }
            match sha256_file(&target) {
                Ok(digest) if digest == item.sha256 => {}
                _ => mismatched.push(item.rel_path.clone()),
            }
        }
        mismatched
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_verifies_raw_integrity_without_modifying_originals() {
        let dir = std::env::temp_dir();
        let pid = std::process::id();
        let path = dir.join(format!("archphoto_raw_test_{pid}.bin"));
        let payload = b"\xff\xd8original-survey-photo-bytes";
        fs::write(&path, payload).unwrap();

        let item = RawItem::from_file(&path, RawKind::Photo).unwrap();
        let mut manifest = ProjectManifest::new("proj-01", "Test Trench").unwrap();
        manifest.register_raw(item);

        assert!(manifest.verify_raw_integrity().is_empty());
        assert_eq!(fs::read(&path).unwrap(), payload);

        // Simulate external modification in temp dir: manifest must detect mismatch.
        fs::write(&path, b"\xff\xd8modified-bytes").unwrap();
        assert_eq!(
            manifest.verify_raw_integrity(),
            vec![path.to_string_lossy().into_owned()]
        );

        let _ = fs::remove_file(&path);
    }

    #[test]
    fn empty_ids_are_refused() {
        assert!(ProjectManifest::new("   ", "title").is_err());
        assert!(RawItem::new("", "abc", RawKind::Photo, 10).is_err());
        assert!(RawItem::new("a.jpg", " ", RawKind::Photo, 10).is_err());
    }
}
