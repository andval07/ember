/* Sieve of Eratosthenes: count primes below 2000 and print the last few. */
char composite[2000];

int main(void) {
    int i, j, count = 0, last = 0;
    for (i = 2; i * i < 2000; i++)
        if (!composite[i])
            for (j = i * i; j < 2000; j += i) composite[j] = 1;
    for (i = 2; i < 2000; i++) {
        if (composite[i]) continue;
        count++;
        last = i;
    }
    for (i = 1990; i < 2000; i++) putchar(composite[i] ? '.' : 'p');
    putchar('\n');
    return (count + last) % 256;
}
