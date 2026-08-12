const skipCheckbox = document.getElementById("landing-skip-checkbox");

skipCheckbox.addEventListener("change", () => {
  if (skipCheckbox.checked) {
    localStorage.setItem("fishaudio_skip_landing", "true");
  } else {
    localStorage.removeItem("fishaudio_skip_landing");
  }
});
