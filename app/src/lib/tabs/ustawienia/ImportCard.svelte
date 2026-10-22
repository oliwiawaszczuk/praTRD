<script lang="ts">
  import { getSetting, setSetting } from "#lib/core/appSettings.svelte.ts";

  const anonymize = $derived(getSetting("anonymizeOnImport", true));
</script>

<label class="opt">
  <input
    type="checkbox"
    checked={anonymize}
    onchange={(e) => setSetting("anonymizeOnImport", e.currentTarget.checked)}
  />
  <div>
    <span class="t">Anonimizuj przy imporcie (domyślnie)</span>
    <span class="d">
      Usuwa z zapisanych tagów i opisu serii: imię i nazwisko, ID, daty, instytucję, lekarzy, UID-y
      i tagi prywatne (profil DICOM PS3.15 Basic). Pacjent dostaje stały pseudonim ANON-xxxx;
      płeć, wiek, wzrost i waga zostają. Ścieżka do plików źródłowych nie jest zapisywana.
      Można to zmienić przy każdym imporcie.
    </span>
  </div>
</label>

<style>
  .opt {
    display: flex;
    gap: 10px;
    cursor: pointer;
  }
  input {
    accent-color: var(--accent);
    margin-top: 3px;
  }
  div {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .t {
    font-size: var(--fs-md);
    color: var(--text);
  }
  .d {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
    line-height: 1.6;
  }
</style>
