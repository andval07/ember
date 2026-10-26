/* Mutual recursion, Ackermann, Towers of Hanoi move count, gcd. */
int is_odd(int n);
int is_even(int n) { if (n == 0) return 1; return is_odd(n - 1); }
int is_odd(int n) { if (n == 0) return 0; return is_even(n - 1); }

int ack(int m, int n) {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}

int moves;
void hanoi(int n, int from, int to, int via) {
    if (n == 0) return;
    hanoi(n - 1, from, via, to);
    moves++;
    hanoi(n - 1, via, to, from);
}

int gcd(int a, int b) { return b == 0 ? a : gcd(b, a % b); }

int many(int a, int b, int c, int d, int e, int f, int g, int h) {
    return a - b + c - d + e - f + g - h;
}

int main(void) {
    hanoi(10, 1, 3, 2);
    putchar(is_even(31) ? 'e' : 'o');
    putchar('\n');
    return (ack(2, 3) + moves + gcd(1071, 462) + many(1, 2, 3, 4, 5, 6, 7, 8)) % 256;
}
