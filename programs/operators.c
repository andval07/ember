/* Precedence, short circuit, shifts, signed division, compound assignment. */
int calls;
int touch(int v) { calls++; return v; }

int main(void) {
    int a = 7, b = -3, r = 0;
    r += a + b * 2 - (a << 2) / 3 % 5;
    r ^= a & 6 | b >> 1;
    r += -17 / 5 + -17 % 5 + 17 / -5 + 17 % -5;
    r += (a > b) + (a == 7) * 2 + !b + ~a;
    r += a < b || touch(1) && touch(0) || touch(2);
    r += 0 && touch(100);
    r += 1 || touch(100);
    r += a ? b ? 4 : 5 : 6;
    r <<= 1; r >>= 1; r |= 64; r &= 0xff; r %= 200; r /= 2; r -= 1; r *= 3;
    return r + calls * 10;
}
