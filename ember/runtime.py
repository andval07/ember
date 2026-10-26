"""Startup code and the helper routines the generated code calls.

RV32I has no multiply or divide, so * / % call these routines. They only
touch a0-a7 and ra, which lets the register allocator keep values in t3-t6
across them.
"""

RUNTIME = """\
.text
_start:
    li sp, 65536
    call main
    li t0, 0x10000000
    sw a0, 0(t0)
.Lrt_hang:
    j .Lrt_hang

putchar:
    li t0, 0x10000004
    sw a0, 0(t0)
    ret

# a0 = a0 * a1 (shift and add)
__mulsi3:
    mv a2, a0
    li a0, 0
.Lrt_mul_loop:
    beqz a1, .Lrt_mul_done
    andi a3, a1, 1
    beqz a3, .Lrt_mul_skip
    add a0, a0, a2
.Lrt_mul_skip:
    slli a2, a2, 1
    srli a1, a1, 1
    j .Lrt_mul_loop
.Lrt_mul_done:
    ret

# unsigned: a0 = a0 / a1, a1 = a0 % a1 (restoring division, 32 steps)
# divide by zero gives q = 0xffffffff, r = a0, like the M extension
__udivmodsi4:
    li a2, 0
    li a3, 0
    li a4, 32
.Lrt_div_loop:
    slli a3, a3, 1
    srli a5, a0, 31
    or a3, a3, a5
    slli a0, a0, 1
    slli a2, a2, 1
    bltu a3, a1, .Lrt_div_skip
    sub a3, a3, a1
    ori a2, a2, 1
.Lrt_div_skip:
    addi a4, a4, -1
    bnez a4, .Lrt_div_loop
    mv a0, a2
    mv a1, a3
    ret

# signed: quotient sign is sign(a ^ b), remainder takes the sign of a
__divsi3:
    addi sp, sp, -16
    sw ra, 12(sp)
    xor a6, a0, a1
    call .Lrt_abs_divmod
    bge a6, zero, .Lrt_div_pos
    neg a0, a0
.Lrt_div_pos:
    lw ra, 12(sp)
    addi sp, sp, 16
    ret

__modsi3:
    addi sp, sp, -16
    sw ra, 12(sp)
    mv a6, a0
    call .Lrt_abs_divmod
    mv a0, a1
    bge a6, zero, .Lrt_mod_pos
    neg a0, a0
.Lrt_mod_pos:
    lw ra, 12(sp)
    addi sp, sp, 16
    ret

# |a0| divmod |a1|; keeps a6, returns through __udivmodsi4
.Lrt_abs_divmod:
    bge a0, zero, .Lrt_abs_a
    neg a0, a0
.Lrt_abs_a:
    bge a1, zero, .Lrt_abs_b
    neg a1, a1
.Lrt_abs_b:
    j __udivmodsi4
"""
