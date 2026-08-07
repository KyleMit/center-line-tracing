# Track 2 — AutoTrace `-centerline` baseline

Slug `autotrace` · branch `claude/centerline-autotrace-qtkuxm` · report §6.2, §18.2

**Verdict up front:** off-the-shelf `autotrace -centerline` **plus our own
width recovery is competitive** — it ties the incumbent on `dinosaur-wide`
(0.02%) and beats it on `landscape-square`. The prior evaluation's conclusion
("autotrace centerline output did not preserve usable stroke widths") was
correct about the symptom and wrong about the implication: the **geometry was
always fine**, and one global fixed width was the entire problem.

_(numbers, tables and the full verdict are filled in below — see Results)_

## Getting the tool

`autotrace` has no apt candidate on this image, so it was built from source:

```bash
git clone --depth 1 https://github.com/autotrace/autotrace
apt-get install -y autoconf automake libtool pkg-config libglib2.0-dev \
                   libpng-dev libexif-dev intltool gettext autopoint \
                   libmagickcore-dev libmagickwand-dev
cd autotrace && sh autogen.sh && ./configure --prefix=/usr/local --without-pstoedit && make -j4
# -> ./autotrace, "AutoTrace version 0.40.0"
```

Three things cost time and are worth writing down:

1. `autogen.sh` only runs `autoreconf`; it does **not** run `configure`.
2. `autopoint` is a separate apt package from `gettext`; without it `autogen.sh`
   dies at `autopoint: not found`.
3. `configure` hard-fails on a missing `pstoedit >= 3.32.0`. `--without-pstoedit`
   is required and costs nothing (it only affects extra output formats).

Total build time was a few minutes. This is not a serious barrier.

### Licensing (report §6.2)

**The report is out of date here, in our favour.** §6.2 says "CLI GPL-2.0;
library LGPL-2.1". In the version actually built (0.40.0), `src/main.c` — the
CLI entry point — carries `SPDX-License-Identifier: LGPL-2.1-or-later`, as does
the SVG writer `src/output-svg.c`. The repo still ships both `COPYING` (GPL) and
`COPYING.LIB` (LGPL), so **this should be confirmed with counsel before
shipping**, but the "the CLI is GPL so we can only shell out, never link"
constraint the report assumes may no longer apply.

This track shells out to the CLI binary and does not link `libautotrace`, which
is the conservative choice under either reading.
