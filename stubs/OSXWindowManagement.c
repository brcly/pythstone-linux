void DisableTabBar() {}
void ShowHideNativeCursor(int show) {}
void SetNativeCursorPosition(float x, float y) {}
int GetCurrentDisplayCount() { return 1; }
void GetDisplayBounds(int display, float *x, float *y, float *w, float *h) {
  if (x) *x = 0; if (y) *y = 0;
  if (w) *w = 1920; if (h) *h = 1080;
}
