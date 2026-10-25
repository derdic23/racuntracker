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

// Buttons with data-confirm ask before submitting (inline onclick is blocked by the CSP)
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-confirm]");
  if (button && !confirm(button.dataset.confirm)) e.preventDefault();
});

// "Proveri mejl sada" can take a while
document.addEventListener("submit", (e) => {
  const button = e.submitter;
  if (button && button.dataset.busy) {
    button.disabled = true;
    button.textContent = button.dataset.busy;
  }
});
