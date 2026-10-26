/* Iterative and recursive Fibonacci, printed in decimal. */
void print_int(int n) {
    char buf[12];
    int i = 0;
    if (n < 0) { putchar('-'); n = -n; }
    do { buf[i++] = '0' + n % 10; n = n / 10; } while (n > 0);
    while (i > 0) putchar(buf[--i]);
    putchar('\n');
}

int fib_rec(int n) { return n < 2 ? n : fib_rec(n - 1) + fib_rec(n - 2); }

int fib_iter(int n) {
    int a = 0, b = 1, i;
    for (i = 0; i < n; i++) { int t = a + b; a = b; b = t; }
    return a;
}

int main(void) {
    int i;
    for (i = 0; i <= 20; i += 5) print_int(fib_rec(i));
    print_int(fib_iter(40));
    return fib_rec(15) % 256;
}
