/* Insertion sort and quicksort on a global array, with a checksum. */
int data[64];
int seed = 12345;

int next_rand(void) {
    seed = seed * 1103515245 + 12345;
    return (seed >> 16) & 0x7fff;
}

void insertion(int *a, int n) {
    int i, j;
    for (i = 1; i < n; i++) {
        int key = a[i];
        for (j = i - 1; j >= 0 && a[j] > key; j--) a[j + 1] = a[j];
        a[j + 1] = key;
    }
}

void swap(int *x, int *y) { int t = *x; *x = *y; *y = t; }

void quick(int *a, int lo, int hi) {
    int pivot, i, j;
    if (lo >= hi) return;
    pivot = a[(lo + hi) / 2];
    i = lo; j = hi;
    while (i <= j) {
        while (a[i] < pivot) i++;
        while (a[j] > pivot) j--;
        if (i <= j) { swap(&a[i], &a[j]); i++; j--; }
    }
    quick(a, lo, j);
    quick(a, i, hi);
}

int sorted(int *a, int n) {
    int i;
    for (i = 1; i < n; i++) if (a[i - 1] > a[i]) return 0;
    return 1;
}

int main(void) {
    int i, sum = 0;
    for (i = 0; i < 64; i++) data[i] = next_rand() % 1000 - 500;
    insertion(data, 32);
    quick(data + 32, 0, 31);
    putchar(sorted(data, 32) ? 'Y' : 'N');
    putchar(sorted(data + 32, 32) ? 'Y' : 'N');
    putchar('\n');
    for (i = 0; i < 64; i++) sum = sum * 31 + data[i];
    return sum & 255;
}
