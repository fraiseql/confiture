//! Confiture Core — the native hasher behind `SchemaBuilder.compute_hash()`.
//!
//! One function, `hash_files`, computing the same digest as the Python path
//! (`(relative path \0 content \0)*` under one SHA-256, in the caller's order,
//! relative to the caller's `base_dir`) with a native SHA-256 and no GIL held
//! while files are read. This crate is a performance accelerator for the
//! Python package, not the start of a Rust port (ARCHITECTURE.md, Decision 8).
use pyo3::prelude::*;

mod hasher;

use hasher::hash_files;

/// Python module definition.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(hash_files, m)?)?;
    Ok(())
}
