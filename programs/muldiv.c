/* Software multiply and divide against identities that must hold. */
int check(int a, int b) {
    int q = a / b, m = a % b;
    return q * b + m == a && (m == 0 || (m < 0) == (a < 0));
}

int main(void) {
    int vals[8] = {0, 1, -1, 7, -7, 1000003, -2147483647, 46341};
    int i, j, ok = 0, prod = 1;
    for (i = 0; i < 8; i++)
        for (j = 0; j < 8; j++)
            if (vals[j] != 0) ok += check(vals[i], vals[j]);
    for (i = 1; i < 12; i++) prod = prod * i;
    putchar(ok == 56 ? 'k' : 'x');
    putchar('\n');
    return (prod / 1000) % 256 + 46341 * 46341 % 97;
}
