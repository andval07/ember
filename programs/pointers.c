/* Pointer arithmetic, pointers to pointers, arrays of pointers, char sign. */
int table[5] = {10, 20, 30, 40, 50};
char *names[3];

void bump(int **pp) { (*pp)++; }

int sum(int *p, int n) { int s = 0; while (n-- > 0) s += *p++; return s; }

int main(void) {
    int *p = table;
    int *q = &table[4];
    char c = 200;
    int x = 7, *px = &x;
    names[0] = "zero"; names[1] = "one"; names[2] = "two";
    bump(&p);
    *px = *px * 3;
    putchar(names[2][1]);
    putchar(*(names[1] + 2));
    putchar('\n');
    return (q - p) + *p + sum(table, 5) + x + c + (c < 0) + sizeof(int *);
}
