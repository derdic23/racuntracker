// Buttons with data-confirm ask before submitting (inline onclick is blocked by the CSP)
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-confirm]");
  if (button && !confirm(button.dataset.confirm)) e.preventDefault();
});

// Podešavanja servera: the edit button unlocks its field; a secret starts empty (empty keeps the saved value)
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-edit]");
  if (!button) return;
  e.preventDefault();
  const input = button.parentElement.querySelector("input");
  input.disabled = false;
  if ("secret" in input.dataset) {
    input.value = "";
    input.placeholder = "nova vrednost, prazno: ostaje stara";
  }
  button.hidden = true;
  input.focus();
});

// "Proveri mejl sada" can take a while
document.addEventListener("submit", (e) => {
  const button = e.submitter;
  if (button && button.dataset.busy) {
    button.disabled = true;
    button.textContent = button.dataset.busy;
  }
});

// Collapsed list sections ("Neplaćeni", "Plaćeni") stay collapsed after reload
document.querySelectorAll("details.section").forEach((d) => {
  const key = "collapsed-" + d.id;
  try {
    if (localStorage.getItem(key)) d.open = false;
  } catch {}
  d.addEventListener("toggle", () => {
    try {
      d.open ? localStorage.removeItem(key) : localStorage.setItem(key, "1");
    } catch {}
  });
});

// Tapping an info icon inside a <label> shows its tip instead of focusing the input
document.addEventListener("click", (e) => {
  if (e.target.closest(".info")) e.preventDefault();
});

// "Na vrh" button in Uputstvo: shown only after scrolling down
const toTop = document.querySelector(".to-top");
if (toTop) {
  const update = () => (toTop.hidden = window.scrollY < 400);
  window.addEventListener("scroll", update, { passive: true });
  update();
  toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
}
