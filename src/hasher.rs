//! SHA-256 over a schema's files, byte-for-byte the digest Python computes.
//!
//! Python's `SchemaBuilder.compute_hash()` streams one hasher over
//! `relative_path \0 content \0` for every file, in discovery order, with the
//! path relative to the builder's `base_dir`. This module does exactly that —
//! not a hash of per-file hashes, not a path relative to the files' common
//! parent — so a wheel install (native) and an editable install (Python) agree
//! on whether a template is stale.

use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;

/// Feed one file into the running digest, exactly as the Python path does.
fn feed(hasher: &mut Sha256, path: &Path, base_dir: &Path) -> std::io::Result<()> {
    let relative = path.strip_prefix(base_dir).unwrap_or(path);
    hasher.update(relative.to_string_lossy().as_bytes());
    hasher.update(b"\x00");
    hasher.update(fs::read(path)?);
    hasher.update(b"\x00");
    Ok(())
}

/// The digest of `files`, in the given order, with paths relative to `base_dir`.
///
/// # Errors
///
/// Returns an `OSError` naming the file when one cannot be read; it never
/// panics, so the Python caller can handle it like any other I/O failure.
#[pyfunction]
#[allow(clippy::needless_pass_by_value)] // Reason: pyo3 hands a #[pyfunction] owned arguments
pub fn hash_files(py: Python<'_>, files: Vec<String>, base_dir: String) -> PyResult<String> {
    py.allow_threads(|| {
        let base = Path::new(&base_dir);
        let mut hasher = Sha256::new();
        for file in &files {
            feed(&mut hasher, Path::new(file), base)
                .map_err(|err| PyOSError::new_err(format!("cannot read {file}: {err}")))?;
        }
        Ok(format!("{:x}", hasher.finalize()))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest_of(files: &[&Path], base: &Path) -> String {
        let mut hasher = Sha256::new();
        for file in files {
            feed(&mut hasher, file, base).expect("readable fixture");
        }
        format!("{:x}", hasher.finalize())
    }

    fn reference(parts: &[(&str, &[u8])]) -> String {
        let mut hasher = Sha256::new();
        for (relative, content) in parts {
            hasher.update(relative.as_bytes());
            hasher.update(b"\x00");
            hasher.update(content);
            hasher.update(b"\x00");
        }
        format!("{:x}", hasher.finalize())
    }

    #[test]
    fn matches_the_python_layout_of_the_digest() {
        let dir = tempfile::tempdir().expect("tempdir");
        let base = dir.path();
        std::fs::create_dir_all(base.join("10_tables")).expect("mkdir");
        let a = base.join("10_tables/010_a.sql");
        let b = base.join("10_tables/020_b.sql");
        std::fs::write(&a, b"CREATE TABLE a (id int);\n").expect("write");
        std::fs::write(&b, "CREATE TABLE b (id int); -- caf\u{e9}\n").expect("write");
        let expected = reference(&[
            ("10_tables/010_a.sql", b"CREATE TABLE a (id int);\n"),
            (
                "10_tables/020_b.sql",
                "CREATE TABLE b (id int); -- caf\u{e9}\n".as_bytes(),
            ),
        ]);
        assert_eq!(digest_of(&[&a, &b], base), expected);
    }

    #[test]
    fn order_and_path_are_part_of_the_digest() {
        let dir = tempfile::tempdir().expect("tempdir");
        let base = dir.path();
        let a = base.join("a.sql");
        let b = base.join("b.sql");
        std::fs::write(&a, b"x").expect("write");
        std::fs::write(&b, b"x").expect("write");
        assert_ne!(digest_of(&[&a, &b], base), digest_of(&[&b, &a], base));
        let elsewhere = dir.path().join("sub");
        assert_ne!(digest_of(&[&a], base), digest_of(&[&a], &elsewhere));
    }

    #[test]
    fn a_missing_file_is_an_error_not_a_panic() {
        let dir = tempfile::tempdir().expect("tempdir");
        let missing = dir.path().join("missing.sql");
        let mut hasher = Sha256::new();
        assert!(feed(&mut hasher, &missing, dir.path()).is_err());
    }
}
