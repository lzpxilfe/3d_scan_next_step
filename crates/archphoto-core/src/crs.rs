//! Coordinate reference systems, vertical datums, and units.
//!
//! AGENTS.md: 좌표계·높이 기준·단위는 명시해야 하며 함부로 섞지 않는다. 추측하지
//! 않는다. These are types, so defaults cannot silently appear.

use std::fmt;

use crate::ContractResult;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LengthUnit {
    Meter,
    Centimeter,
    Millimeter,
    Foot,
}

impl LengthUnit {
    /// Meters per one unit.
    pub fn meters_per_unit(self) -> f64 {
        match self {
            LengthUnit::Meter => 1.0,
            LengthUnit::Centimeter => 0.01,
            LengthUnit::Millimeter => 0.001,
            LengthUnit::Foot => 0.3048,
        }
    }

    /// Multiply a length in `self` by this to express the same length in `to`.
    pub fn factor_to(self, to: LengthUnit) -> f64 {
        self.meters_per_unit() / to.meters_per_unit()
    }

    pub fn is_metric(self) -> bool {
        !matches!(self, LengthUnit::Foot)
    }
}

impl fmt::Display for LengthUnit {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            LengthUnit::Meter => "m",
            LengthUnit::Centimeter => "cm",
            LengthUnit::Millimeter => "mm",
            LengthUnit::Foot => "ft",
        };
        f.write_str(s)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerticalDatum {
    Ellipsoidal,
    Orthometric,
    Local,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AxisOrder {
    EastNorth,
    NorthEast,
}

/// CRS id + unit + height reference bound together. The CRS id is required at
/// construction — there is no default CRS anywhere in the codebase.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpatialFrame {
    pub crs_id: String,
    pub unit: LengthUnit,
    pub axis_order: AxisOrder,
    pub vertical_datum: VerticalDatum,
    pub geoid_model: Option<String>,
}

impl SpatialFrame {
    /// Ported from Python `SpatialFrame.__post_init__`: an explicit CRS id is
    /// mandatory. Use "LOCAL:<name>" for site grids; never blank.
    pub fn new(crs_id: impl Into<String>, unit: LengthUnit) -> ContractResult<Self> {
        let crs_id = crs_id.into();
        if crs_id.is_empty() {
            return Err("SpatialFrame.crs_id must be set explicitly".into());
        }
        Ok(SpatialFrame {
            crs_id,
            unit,
            axis_order: AxisOrder::EastNorth,
            vertical_datum: VerticalDatum::Unknown,
            geoid_model: None,
        })
    }

    pub fn with_vertical_datum(mut self, datum: VerticalDatum) -> Self {
        self.vertical_datum = datum;
        self
    }

    pub fn is_metric(&self) -> bool {
        self.unit.is_metric()
    }
}

impl fmt::Display for SpatialFrame {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{} · {} · {:?} · {:?}",
            self.crs_id, self.unit, self.axis_order, self.vertical_datum
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_factors_convert_between_metric_and_imperial() {
        assert!((LengthUnit::Centimeter.factor_to(LengthUnit::Meter) - 0.01).abs() < 1e-12);
        assert!((LengthUnit::Meter.factor_to(LengthUnit::Foot) - 1.0 / 0.3048).abs() < 1e-12);
        assert_eq!(
            LengthUnit::Millimeter.factor_to(LengthUnit::Millimeter),
            1.0
        );
    }

    #[test]
    fn feet_are_not_metric() {
        assert!(!LengthUnit::Foot.is_metric());
        assert!(LengthUnit::Millimeter.is_metric());
    }

    #[test]
    fn frame_requires_crs_id() {
        let frame = SpatialFrame::new("EPSG:5186", LengthUnit::Meter)
            .unwrap()
            .with_vertical_datum(VerticalDatum::Orthometric);
        assert_eq!(frame.crs_id, "EPSG:5186");
        assert_eq!(frame.unit, LengthUnit::Meter);
        assert_eq!(frame.vertical_datum, VerticalDatum::Orthometric);
        assert!(frame.is_metric());
        // 빈 CRS 식별자는 좌표계 없는 좌표다 — 존재해서는 안 된다.
        let err = SpatialFrame::new("", LengthUnit::Meter).unwrap_err();
        assert!(err.contains("crs_id must be set explicitly"), "{err}");
    }

    #[test]
    fn height_references_are_distinct_types() {
        // 서로 다른 높이 기준은 서로 바꿔 쓸 수 없는 값이다.
        assert_ne!(VerticalDatum::Orthometric, VerticalDatum::Ellipsoidal);
        assert_ne!(VerticalDatum::Unknown, VerticalDatum::Orthometric);
        assert_ne!(AxisOrder::EastNorth, AxisOrder::NorthEast);
    }
}
