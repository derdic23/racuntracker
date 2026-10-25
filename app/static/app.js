// "Kopiraj" buttons. navigator.clipboard works only on HTTPS/localhost, so fall back to execCommand.
document.addEventListener("click", async (e) => {
  const button = e.target.closest("[data-copy]");
  if (!button) return;
  const input = button.previousElementSibling;
  try {
    await navigator.clipboard.writeText(input.value);
  } catch {
    input.select();
    document.execCommand("copy");
  }
  button.textContent = "Kopirano";
  setTimeout(() => (button.textContent = "Kopiraj"), 1500);
});
