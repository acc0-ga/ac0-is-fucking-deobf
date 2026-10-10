package x;

import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

public class VmpRuntime {
    private static final Object SENT = new Object();
    private static final Map<String, Class<?>> CLS = new HashMap<String, Class<?>>();
    private static final Map<String, Method> MTH = new HashMap<String, Method>();
    private static final Map<String, Field> FLD = new HashMap<String, Field>();

    public static Object exec(String prog, Object[] consts, Object[] locals) throws Throwable {
        char[] p = prog.toCharArray();
        int dk = p[0] - 1;
        for (int i = 1; i < p.length; i++) {
            p[i] = (char) (((p[i] - 1) ^ dk) + 1);
        }
        int maxStack = ((p[2] - 1) << 8) | (p[3] - 1);
        Object[] st = new Object[maxStack + 8];
        int sp = 0;
        int ip = 4;
        while (true) {
            int op = p[ip++] - 1;
            switch (op) {
            case 0x00:
                break;
            case 0x01:
                st[sp++] = null;
                break;
            case 0x02: case 0x03: case 0x04: case 0x05: case 0x06: case 0x07: case 0x08:
                st[sp++] = Integer.valueOf(op - 3);
                break;
            case 0x09: case 0x0A:
                st[sp++] = Long.valueOf(op - 9);
                st[sp++] = SENT;
                break;
            case 0x10:
                st[sp++] = Integer.valueOf((byte) (p[ip++] - 1));
                break;
            case 0x11: {
                int v = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = Integer.valueOf((short) v);
                break;
            }
            case 0x12: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = consts[ci];
                break;
            }
            case 0x14: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = consts[ci];
                st[sp++] = SENT;
                break;
            }
            case 0x15: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = locals[n];
                break;
            }
            case 0x16: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = locals[n];
                st[sp++] = SENT;
                break;
            }
            case 0x19: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                st[sp++] = locals[n];
                break;
            }
            case 0x36: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                locals[n] = st[--sp];
                break;
            }
            case 0x37: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                sp -= 2;
                locals[n] = st[sp];
                break;
            }
            case 0x3A: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                locals[n] = st[--sp];
                break;
            }
            case 0x2E: case 0x32: case 0x33: case 0x34: case 0x35: {
                sp -= 2;
                int idx = ((Integer) st[sp + 1]).intValue();
                Object v = Array.get(st[sp], idx);
                if (op == 0x33) {
                    if (v instanceof Boolean) {
                        v = Integer.valueOf(((Boolean) v).booleanValue() ? 1 : 0);
                    } else {
                        v = Integer.valueOf(((Byte) v).byteValue());
                    }
                } else if (op == 0x34) {
                    v = Integer.valueOf(((Character) v).charValue());
                } else if (op == 0x35) {
                    v = Integer.valueOf(((Short) v).shortValue());
                }
                st[sp] = v;
                sp++;
                break;
            }
            case 0x2F: {
                sp -= 2;
                int idx = ((Integer) st[sp + 1]).intValue();
                Object v = Array.get(st[sp], idx);
                st[sp] = v;
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x4F: case 0x53: case 0x54: case 0x55: case 0x56: {
                sp -= 3;
                Object val = st[sp + 2];
                int idx = ((Integer) st[sp + 1]).intValue();
                Object arr = st[sp];
                Class<?> ct = arr.getClass().getComponentType();
                Object w;
                if (ct == int.class) {
                    w = val;
                } else if (ct == byte.class) {
                    w = Byte.valueOf((byte) ((Integer) val).intValue());
                } else if (ct == boolean.class) {
                    w = Boolean.valueOf(((Integer) val).intValue() != 0);
                } else if (ct == char.class) {
                    w = Character.valueOf((char) ((Integer) val).intValue());
                } else if (ct == short.class) {
                    w = Short.valueOf((short) ((Integer) val).intValue());
                } else {
                    w = val;
                }
                Array.set(arr, idx, w);
                break;
            }
            case 0x50: {
                sp -= 4;
                Object val = st[sp + 2];
                int idx = ((Integer) st[sp + 1]).intValue();
                Array.set(st[sp], idx, val);
                break;
            }
            case 0x57:
                sp--;
                break;
            case 0x58:
                sp -= 2;
                break;
            case 0x59:
                st[sp] = st[sp - 1];
                sp++;
                break;
            case 0x5A: {
                Object a = st[sp - 2];
                Object b = st[sp - 1];
                st[sp - 2] = b;
                st[sp - 1] = a;
                st[sp] = b;
                sp++;
                break;
            }
            case 0x5B: {
                Object a = st[sp - 3];
                Object b = st[sp - 2];
                Object c = st[sp - 1];
                st[sp - 3] = c;
                st[sp - 2] = a;
                st[sp - 1] = b;
                st[sp] = c;
                sp++;
                break;
            }
            case 0x5C:
                st[sp] = st[sp - 2];
                st[sp + 1] = st[sp - 1];
                sp += 2;
                break;
            case 0x5D: {
                Object a = st[sp - 3];
                Object b = st[sp - 2];
                Object c = st[sp - 1];
                st[sp] = b;
                st[sp + 1] = c;
                st[sp - 3] = b;
                st[sp - 2] = c;
                st[sp - 1] = a;
                sp += 2;
                break;
            }
            case 0x5E: {
                Object a = st[sp - 4];
                Object b = st[sp - 3];
                Object c = st[sp - 2];
                Object d = st[sp - 1];
                st[sp] = c;
                st[sp + 1] = d;
                st[sp - 4] = c;
                st[sp - 3] = d;
                st[sp - 2] = a;
                st[sp - 1] = b;
                sp += 2;
                break;
            }
            case 0x5F: {
                Object a = st[sp - 2];
                st[sp - 2] = st[sp - 1];
                st[sp - 1] = a;
                break;
            }
            case 0x60: case 0x64: case 0x68: case 0x6C: case 0x70: {
                sp -= 2;
                int b = ((Integer) st[sp + 1]).intValue();
                int a = ((Integer) st[sp]).intValue();
                int r;
                switch (op) {
                case 0x60: r = a + b; break;
                case 0x64: r = a - b; break;
                case 0x68: r = a * b; break;
                case 0x6C: r = a / b; break;
                default: r = a % b; break;
                }
                st[sp] = Integer.valueOf(r);
                sp++;
                break;
            }
            case 0x74: {
                sp--;
                st[sp] = Integer.valueOf(-((Integer) st[sp]).intValue());
                break;
            }
            case 0x78: case 0x7A: case 0x7C: case 0x7E: case 0x80: case 0x82: {
                sp -= 2;
                int b = ((Integer) st[sp + 1]).intValue();
                int a = ((Integer) st[sp]).intValue();
                int r;
                switch (op) {
                case 0x78: r = a << b; break;
                case 0x7A: r = a >> b; break;
                case 0x7C: r = a >>> b; break;
                case 0x7E: r = a & b; break;
                case 0x80: r = a | b; break;
                default: r = a ^ b; break;
                }
                st[sp] = Integer.valueOf(r);
                sp++;
                break;
            }
            case 0x61: case 0x65: case 0x69: case 0x6D: case 0x71: {
                sp -= 4;
                long b = ((Long) st[sp + 2]).longValue();
                long a = ((Long) st[sp]).longValue();
                long r;
                switch (op) {
                case 0x61: r = a + b; break;
                case 0x65: r = a - b; break;
                case 0x69: r = a * b; break;
                case 0x6D: r = a / b; break;
                default: r = a % b; break;
                }
                st[sp] = Long.valueOf(r);
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x75: {
                sp -= 2;
                st[sp] = Long.valueOf(-((Long) st[sp]).longValue());
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x79: case 0x7B: case 0x7D: {
                sp -= 3;
                int s = ((Integer) st[sp + 2]).intValue();
                long a = ((Long) st[sp]).longValue();
                long r;
                if (op == 0x79) {
                    r = a << s;
                } else if (op == 0x7B) {
                    r = a >> s;
                } else {
                    r = a >>> s;
                }
                st[sp] = Long.valueOf(r);
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x7F: case 0x81: case 0x83: {
                sp -= 4;
                long b = ((Long) st[sp + 2]).longValue();
                long a = ((Long) st[sp]).longValue();
                long r;
                if (op == 0x7F) {
                    r = a & b;
                } else if (op == 0x81) {
                    r = a | b;
                } else {
                    r = a ^ b;
                }
                st[sp] = Long.valueOf(r);
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x84: {
                int n = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                int d = ((p[ip + 2] - 1) << 8) | (p[ip + 3] - 1);
                ip += 4;
                locals[n] = Integer.valueOf(((Integer) locals[n]).intValue() + (short) d);
                break;
            }
            case 0x85: {
                sp--;
                int a = ((Integer) st[sp]).intValue();
                st[sp] = Long.valueOf(a);
                st[sp + 1] = SENT;
                sp += 2;
                break;
            }
            case 0x88: {
                sp -= 2;
                long a = ((Long) st[sp]).longValue();
                st[sp] = Integer.valueOf((int) a);
                sp++;
                break;
            }
            case 0x91: {
                sp--;
                st[sp] = Integer.valueOf(((Integer) st[sp]).intValue() << 24 >> 24);
                break;
            }
            case 0x92: {
                sp--;
                st[sp] = Integer.valueOf(((Integer) st[sp]).intValue() & 0xFFFF);
                break;
            }
            case 0x93: {
                sp--;
                st[sp] = Integer.valueOf(((Integer) st[sp]).intValue() << 16 >> 16);
                break;
            }
            case 0x94: {
                sp -= 4;
                long b = ((Long) st[sp + 2]).longValue();
                long a = ((Long) st[sp]).longValue();
                st[sp] = Integer.valueOf(a < b ? -1 : (a == b ? 0 : 1));
                sp++;
                break;
            }
            case 0x99: case 0x9A: case 0x9B: case 0x9C: case 0x9D: case 0x9E: {
                int t = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                sp--;
                int v = ((Integer) st[sp]).intValue();
                boolean go;
                switch (op) {
                case 0x99: go = v == 0; break;
                case 0x9A: go = v != 0; break;
                case 0x9B: go = v < 0; break;
                case 0x9C: go = v >= 0; break;
                case 0x9D: go = v > 0; break;
                default: go = v <= 0; break;
                }
                if (go) {
                    ip = t;
                }
                break;
            }
            case 0x9F: case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: {
                int t = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                sp -= 2;
                int b = ((Integer) st[sp + 1]).intValue();
                int a = ((Integer) st[sp]).intValue();
                boolean go;
                switch (op) {
                case 0x9F: go = a == b; break;
                case 0xA0: go = a != b; break;
                case 0xA1: go = a < b; break;
                case 0xA2: go = a >= b; break;
                case 0xA3: go = a > b; break;
                default: go = a <= b; break;
                }
                if (go) {
                    ip = t;
                }
                break;
            }
            case 0xA5: case 0xA6: {
                int t = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                sp -= 2;
                if ((st[sp] == st[sp + 1]) == (op == 0xA5)) {
                    ip = t;
                }
                break;
            }
            case 0xA7: {
                ip = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                break;
            }
            case 0xC6: case 0xC7: {
                int t = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                sp--;
                if ((st[sp] == null) == (op == 0xC6)) {
                    ip = t;
                }
                break;
            }
            case 0xAA: {
                int def = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                int low = ((p[ip + 2] - 1) << 24) | ((p[ip + 3] - 1) << 16)
                        | ((p[ip + 4] - 1) << 8) | (p[ip + 5] - 1);
                int cnt = ((p[ip + 6] - 1) << 8) | (p[ip + 7] - 1);
                ip += 8;
                sp--;
                int k = ((Integer) st[sp]).intValue();
                if (k < low || k - low >= cnt) {
                    ip = def;
                } else {
                    int o = ip + 2 * (k - low);
                    ip = ((p[o] - 1) << 8) | (p[o + 1] - 1);
                }
                break;
            }
            case 0xAB: {
                int def = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                int np = ((p[ip + 2] - 1) << 8) | (p[ip + 3] - 1);
                ip += 4;
                sp--;
                int k = ((Integer) st[sp]).intValue();
                int nt = def;
                for (int j = 0; j < np; j++) {
                    int key = ((p[ip] - 1) << 24) | ((p[ip + 1] - 1) << 16)
                            | ((p[ip + 2] - 1) << 8) | (p[ip + 3] - 1);
                    int off = ((p[ip + 4] - 1) << 8) | (p[ip + 5] - 1);
                    ip += 6;
                    if (key == k) {
                        nt = off;
                        break;
                    }
                }
                ip = nt;
                break;
            }
            case 0xAC:
                return st[--sp];
            case 0xAD:
                sp -= 2;
                return st[sp];
            case 0xB0:
                return st[--sp];
            case 0xB1:
                return null;
            case 0xBE: {
                sp--;
                st[sp] = Integer.valueOf(Array.getLength(st[sp]));
                sp++;
                break;
            }
            case 0xB2: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                String[] m = (String[]) consts[ci];
                Field f = fld(m[0], m[1], m[2]);
                Object v = f.get(null);
                sp = pushVal(st, sp, v, m[2].charAt(0));
                break;
            }
            case 0xB3: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                String[] m = (String[]) consts[ci];
                Field f = fld(m[0], m[1], m[2]);
                sp = popArg(st, sp, m[2].charAt(0));
                Object v = st[sp];
                sp++;
                f.set(null, toArg(m[2].charAt(0), v));
                break;
            }
            case 0xB4: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                String[] m = (String[]) consts[ci];
                Field f = fld(m[0], m[1], m[2]);
                sp--;
                Object o = st[sp];
                Object v = f.get(o);
                sp = pushVal(st, sp, v, m[2].charAt(0));
                break;
            }
            case 0xB5: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                String[] m = (String[]) consts[ci];
                Field f = fld(m[0], m[1], m[2]);
                sp = popArg(st, sp, m[2].charAt(0));
                Object v = st[sp];
                sp++;
                sp--;
                Object o = st[sp];
                f.set(o, toArg(m[2].charAt(0), v));
                break;
            }
            case 0xB6: case 0xB8: {
                int ci = ((p[ip] - 1) << 8) | (p[ip + 1] - 1);
                ip += 2;
                String[] m = (String[]) consts[ci];
                String ds = m[2];
                int np = countParams(ds);
                Object[] args = new Object[np];
                for (int j = np - 1; j >= 0; j--) {
                    char t = paramType(ds, j);
                    if (t == 'J') {
                        sp -= 2;
                        args[j] = toArg(t, st[sp]);
                    } else {
                        sp -= 1;
                        args[j] = toArg(t, st[sp]);
                    }
                }
                Object recv = null;
                if (op == 0xB6) {
                    sp--;
                    recv = st[sp];
                }
                Method mt = mth(m[0], m[1], ds);
                Object r;
                try {
                    r = mt.invoke(recv, args);
                } catch (InvocationTargetException e) {
                    throw e.getTargetException();
                }
                sp = pushVal(st, sp, r, ds.charAt(ds.length() - 1));
                break;
            }
            default:
                throw new IllegalStateException("vmp: bad opcode " + op);
            }
        }
    }

    private static int popArg(Object[] st, int sp, char t) {
        if (t == 'J') {
            return sp - 2;
        }
        return sp - 1;
    }

    private static int pushVal(Object[] st, int sp, Object v, char t) {
        if (t == 'V') {
            return sp;
        }
        if (t == 'J') {
            st[sp++] = v;
            st[sp++] = SENT;
            return sp;
        }
        if (t == 'Z') {
            st[sp++] = Integer.valueOf(((Boolean) v).booleanValue() ? 1 : 0);
            return sp;
        }
        if (t == 'B') {
            st[sp++] = Integer.valueOf(((Byte) v).byteValue());
            return sp;
        }
        if (t == 'C') {
            st[sp++] = Integer.valueOf(((Character) v).charValue());
            return sp;
        }
        if (t == 'S') {
            st[sp++] = Integer.valueOf(((Short) v).shortValue());
            return sp;
        }
        st[sp++] = v;
        return sp;
    }

    private static Object toArg(char t, Object v) {
        if (t == 'Z') {
            return Boolean.valueOf(((Integer) v).intValue() != 0);
        }
        if (t == 'B') {
            return Byte.valueOf((byte) ((Integer) v).intValue());
        }
        if (t == 'C') {
            return Character.valueOf((char) ((Integer) v).intValue());
        }
        if (t == 'S') {
            return Short.valueOf((short) ((Integer) v).intValue());
        }
        return v;
    }

    private static int countParams(String d) {
        int c = 0;
        int i = 1;
        while (d.charAt(i) != ')') {
            c++;
            i = tEnd(d, i);
        }
        return c;
    }

    private static char paramType(String d, int j) {
        int i = 1;
        int k = 0;
        while (d.charAt(i) != ')') {
            if (k == j) {
                return d.charAt(i);
            }
            i = tEnd(d, i);
            k++;
        }
        return 'L';
    }

    private static int tEnd(String d, int i) {
        char c = d.charAt(i);
        if (c == 'L') {
            return d.indexOf(';', i) + 1;
        }
        if (c == '[') {
            return tEnd(d, i + 1);
        }
        return i + 1;
    }

    private static Class<?> cls(String in) throws ClassNotFoundException {
        Class<?> c = CLS.get(in);
        if (c == null) {
            c = Class.forName(in.replace('/', '.'), false, VmpRuntime.class.getClassLoader());
            CLS.put(in, c);
        }
        return c;
    }

    private static Class<?>[] paramTypes(String d) throws ClassNotFoundException {
        int n = countParams(d);
        Class<?>[] r = new Class<?>[n];
        int i = 1;
        int k = 0;
        while (d.charAt(i) != ')') {
            r[k++] = typeClass(d, i);
            i = tEnd(d, i);
        }
        return r;
    }

    private static Class<?> typeClass(String d, int i) throws ClassNotFoundException {
        char c = d.charAt(i);
        if (c == 'I') return int.class;
        if (c == 'J') return long.class;
        if (c == 'Z') return boolean.class;
        if (c == 'B') return byte.class;
        if (c == 'C') return char.class;
        if (c == 'S') return short.class;
        if (c == 'F') return float.class;
        if (c == 'D') return double.class;
        if (c == 'L') return cls(d.substring(i + 1, d.indexOf(';', i)));
        return cls(d.substring(i));
    }

    private static Method mth(String owner, String name, String ds) throws Throwable {
        String key = owner + " " + name + " " + ds;
        Method m = MTH.get(key);
        if (m == null) {
            Class<?> c = cls(owner);
            m = findMethod(c, name, paramTypes(ds));
            try {
                m.setAccessible(true);
            } catch (Throwable ignored) {
            }
            MTH.put(key, m);
        }
        return m;
    }

    private static Method findMethod(Class<?> c, String name, Class<?>[] pt) throws NoSuchMethodException {
        for (Class<?> k = c; k != null; k = k.getSuperclass()) {
            try {
                return k.getDeclaredMethod(name, pt);
            } catch (NoSuchMethodException ignored) {
            }
        }
        for (Class<?> k = c; k != null; k = k.getSuperclass()) {
            for (Class<?> i : k.getInterfaces()) {
                try {
                    return findMethod(i, name, pt);
                } catch (NoSuchMethodException ignored) {
                }
            }
        }
        throw new NoSuchMethodException(c.getName() + "." + name);
    }

    private static Field fld(String owner, String name, String ds) throws Throwable {
        String key = owner + " " + name + " " + ds;
        Field f = FLD.get(key);
        if (f == null) {
            Class<?> c = cls(owner);
            f = findField(c, name);
            if (f == null || !classDesc(f.getType()).equals(ds)) {
                throw new NoSuchFieldException(owner + "." + name);
            }
            try {
                f.setAccessible(true);
            } catch (Throwable ignored) {
            }
            FLD.put(key, f);
        }
        return f;
    }

    private static Field findField(Class<?> c, String name) {
        for (Class<?> k = c; k != null; k = k.getSuperclass()) {
            try {
                return k.getDeclaredField(name);
            } catch (NoSuchFieldException ignored) {
            }
        }
        for (Class<?> k = c; k != null; k = k.getSuperclass()) {
            for (Class<?> i : k.getInterfaces()) {
                Field f = findField(i, name);
                if (f != null) {
                    return f;
                }
            }
        }
        return null;
    }

    private static String classDesc(Class<?> c) {
        if (c.isPrimitive()) {
            if (c == int.class) return "I";
            if (c == long.class) return "J";
            if (c == boolean.class) return "Z";
            if (c == byte.class) return "B";
            if (c == char.class) return "C";
            if (c == short.class) return "S";
            if (c == float.class) return "F";
            if (c == double.class) return "D";
            return "V";
        }
        if (c.isArray()) {
            return "[" + classDesc(c.getComponentType());
        }
        return "L" + c.getName().replace('.', '/') + ";";
    }
}
