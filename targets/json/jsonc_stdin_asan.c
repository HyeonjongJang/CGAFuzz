#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <json-c/json_tokener.h>

int main(void) {
  size_t cap = 1 << 20; // 1MB
  size_t n = 0;
  uint8_t *buf = (uint8_t*)malloc(cap);
  if (!buf) return 1;
  while (1) {
    if (n == cap) {
      size_t ncap = cap << 1;
      uint8_t *nb = (uint8_t*)realloc(buf, ncap);
      if (!nb) { free(buf); return 1; }
      buf = nb; cap = ncap;
    }
    ssize_t r = read(STDIN_FILENO, buf + n, cap - n);
    if (r < 0) { free(buf); return 1; }
    if (r == 0) break;
    n += (size_t)r;
  }
  static const char kMin[] = "{}";
  const char *data = (n ? (const char*)buf : kMin);
  int len = (n ? (int)n : (int)sizeof(kMin)-1);

  struct json_tokener *tok = json_tokener_new();
  if (tok) {
    json_object *obj = json_tokener_parse_ex(tok, data, len);
    (void)json_tokener_get_error(tok);
    if (obj) json_object_put(obj);
    json_tokener_free(tok);
  }
  free(buf);
  return 0;
}
