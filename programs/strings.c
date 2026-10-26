/* String routines written by hand: length, copy, compare, reverse. */
int len(char *s) { char *p = s; while (*p) p++; return p - s; }

void copy(char *dst, char *src) { while ((*dst++ = *src++) != 0) {} }

int cmp(char *a, char *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a - *b;
}

void reverse(char *s) {
    char *e = s + len(s) - 1;
    while (s < e) { char t = *s; *s++ = *e; *e-- = t; }
}

void puts_(char *s) { while (*s) putchar(*s++); putchar('\n'); }

char *greeting = "hello, ember";

int main(void) {
    char buf[32];
    char word[] = "risc";
    copy(buf, greeting);
    reverse(buf);
    puts_(buf);
    puts_(word);
    word[0] = 'R';
    puts_(word);
    putchar(cmp("abc", "abd") < 0 ? '<' : '>');
    putchar(cmp("b", "a") > 0 ? '>' : '<');
    putchar(cmp(buf, buf) == 0 ? '=' : '!');
    putchar('\n');
    return len(greeting) + sizeof(word) + sizeof buf;
}
