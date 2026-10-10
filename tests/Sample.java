import java.util.*;
import java.util.function.*;

public class Sample {
    enum Color { RED, GREEN, BLUE }

    @interface Meta {
        String value();
        int num() default 7;
    }

    static class Inner {
        private int x;

        Inner(int x) { this.x = x; }

        int getX() { return x; }
    }

    private final List<String> items = new ArrayList<>();
    private long seed = 0x5DEECE66DL;

    @Meta(value = "hello", num = 3)
    public static String annotated() {
        return "annotation-worked";
    }

    public int compute(int n) {
        int acc = 0;
        switch (n % 5) {
            case 0: acc += 3; break;
            case 1: acc += 7; break;
            case 2: acc += 11; break;
            case 3: acc += 13; break;
            default: acc += 17;
        }
        for (int i = 0; i < n; i++) {
            if ((i & 1) == 0) {
                acc += i * 3;
            } else {
                acc -= i;
            }
        }
        try {
            if (n > 100) {
                throw new IllegalStateException("too big: " + n);
            }
            acc = risky(acc, n);
        } catch (IllegalStateException e) {
            acc = e.getMessage().length();
        } finally {
            acc ^= 0x55;
        }
        return acc;
    }

    private int risky(int a, int b) {
        if (b == 0) {
            throw new IllegalArgumentException("zero");
        }
        return a / b + (a % b);
    }

    public long mixed(long l, double d, float f, boolean z, char c, byte by, short sh) {
        long r = l * 31 + (long) d;
        r += (long) (f * 2.5f);
        r ^= z ? 0x1000L : 0x2000L;
        r += c + by + sh;
        StringBuilder sb = new StringBuilder();
        sb.append("val=").append(r).append('/').append(d);
        return r + sb.length();
    }

    public String build(String a, String b) {
        return a + "-" + b + "!" + a.length() + b.hashCode();
    }

    public List<String> generics(List<? extends Number> in) {
        List<String> out = new ArrayList<>();
        for (Number x : in) {
            out.add(x.getClass().getSimpleName() + ":" + x.doubleValue());
        }
        Map<String, List<Integer>> m = new LinkedHashMap<>();
        m.put("k", Arrays.asList(1, 2, 3));
        out.add(m.toString());
        return out;
    }

    public int[] arrays(int n) {
        int[][] grid = new int[n][n];
        String[] names = new String[]{"alpha", "beta", "gamma"};
        byte[] blob = new byte[]{1, 2, 3, 4, 5};
        long[] big = new long[n + 1];
        double[] dbl = new double[n + 1];
        for (int i = 0; i < n; i++) {
            grid[i][i] = i * i;
            big[i] = (long) i * i * i;
            dbl[i] = Math.sqrt(i);
        }
        int sum = 0;
        for (int[] row : grid) {
            for (int v : row) sum += v;
        }
        for (String s : names) sum += s.length();
        sum += blob.length + (int) big[0] + (int) dbl[0];
        return new int[]{sum, n};
    }

    public Color pick(int n) {
        Color[] all = Color.values();
        return all[n % all.length];
    }

    public String lambdaish(List<String> list) {
        Function<String, String> up = s -> s.toUpperCase() + "::" + s.length();
        Predicate<String> longish = s -> s.length() > 3;
        list.removeIf(longish);
        List<String> mapped = new ArrayList<>();
        list.forEach(s -> mapped.add(up.apply(s)));
        Comparator<String> cmp = (x, y) -> Integer.compare(y.length(), x.length());
        mapped.sort(cmp);
        String joined = String.join(",", mapped);
        return joined + "|" + Color.valueOf("RED").name();
    }

    public int loops(int n) {
        int i = 0;
        outer:
        while (i < n) {
            for (int j = 0; j < n; j++) {
                if (j == 5) continue outer;
                if (j == 9) break outer;
                i += j;
            }
            i++;
        }
        do {
            i--;
        } while (i > n);
        return i;
    }

    public synchronized int syncAdd(int v) {
        seed += v;
        synchronized (this) {
            seed ^= (seed << 7);
        }
        return (int) seed;
    }

    public static void main(String[] args) {
        Sample s = new Sample();
        int r = s.compute(args.length + 10);
        r += (int) s.mixed(123456789L, 2.75, 1.5f, true, 'Z', (byte) -3, (short) 1000);
        r += s.arrays(4)[0];
        r += s.loops(20);
        r += s.syncAdd(3);
        List<String> l = new ArrayList<>(Arrays.asList("aa", "bbbb", "c", "dddddd"));
        String out = s.lambdaish(l);
        String built = s.build("x", "y");
        System.out.println("RESULT r=" + r);
        System.out.println("RESULT out=" + out);
        System.out.println("RESULT built=" + built);
        System.out.println("RESULT ann=" + annotated());
        System.out.println("RESULT color=" + s.pick(1));
        System.out.println("RESULT gen=" + s.generics(Arrays.asList(1, 2.5, 3.0f)).size());
        System.out.println("RESULT inner=" + new Inner(42).getX());
    }
}
