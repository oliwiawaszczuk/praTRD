fn main() {
    // Bake the project root (…/praTRD) into dev builds: the sidecar runs from there with uv
    // and keeps workspaces/ next to the code.
    let manifest = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let root = manifest.parent().unwrap().parent().unwrap();
    println!("cargo:rustc-env=PRATRD_ROOT={}", root.display());
    tauri_build::build()
}
