//! Confiture Core - Rust performance layer for PostgreSQL migrations
//!
//! This crate provides high-performance file operations and schema building
//! to accelerate the Python confiture tool by 10-50x.

use pyo3::prelude::*;

mod builder;
mod hasher;

use builder::build_schema;
use hasher::hash_files;

/// Python module definition
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_schema, m)?)?;
    m.add_function(wrap_pyfunction!(hash_files, m)?)?;
    Ok(())
}
