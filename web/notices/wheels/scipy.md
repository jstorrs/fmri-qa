For: scipy 1.18.0
Pyodide: 314.0.7
Emscripten: 5.0.3

### SciPy's bundled code (LICENSES_bundled.txt)
Licence: as listed
Source: https://github.com/scipy/scipy/blob/v1.18.0/LICENSES_bundled.txt (PyPI wheels append it to LICENSE.txt; this Pyodide build does not)

----

The SciPy repository and source distributions bundle a number of libraries that
are compatibly licensed.  We list these here.


Name: fast_matrix_market
Files: scipy/io/_fast_matrix_market/*
License: BSD-2-Clause
  For details, see scipy/io/_fast_matrix_market/LICENSE.txt

Name: pystreambuf
Files: scipy/io/_fast_matrix_market/src/pystreambuf.h
License: BSD-3-Clause
  For details, see the header inside scipy/io/_fast_matrix_market/src/pystreambuf.h

Name: fast_float
Files: scipy/io/_fast_matrix_market/fast_matrix_market/dependencies/fast_float/*
License: MIT
  For details, see scipy/io/_fast_matrix_market/fast_matrix_market/dependencies/fast_float/LICENSE-MIT

Name: ryu
Files: scipy/io/_fast_matrix_market/fast_matrix_market/dependencies/ryu/*
License: BSL-1.0
  For details, see scipy/io/_fast_matrix_market/fast_matrix_market/dependencies/ryu/LICENSE-Boost

Name: L-BFGS-B
Files: scipy/optimize/lbfgsb/[__lbfgsb.h,__lbfgsb.c]
License: BSD-3-Clause
  For details, see scipy/optimize/__lbfgsb.c

Name: LAPJVsp
Files: scipy/sparse/csgraph/_matching.pyx
License: BSD-3-Clause
Copyright 1987-, A. Volgenant/Amsterdam School of Economics,
                 University of Amsterdam

  Distributed under 3-clause BSD license with permission from
  University of Amsterdam.

  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the following conditions are met:

  1. Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

  2. Redistributions in binary form must reproduce the above copyright notice,
     this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

  3. Neither the name of the copyright holder nor the names of its contributors
     may be used to endorse or promote products derived from this software
    without specific prior written permission.

  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
  POSSIBILITY OF SUCH DAMAGE.


Name: SuperLU
Files: scipy/sparse/linalg/_dsolve/SuperLU/*
License: BSD-3-Clause
  For details, see scipy/sparse/linalg/_dsolve/SuperLU/License.txt

Name: ARPACK
Files: scipy/sparse/linalg/_eigen/arpack/ARPACK/*
License: BSD-3-Clause
  For details, see scipy/sparse/linalg/_eigen/arpack/ARPACK/COPYING

Name: Qhull
Files: subprojects/qhull_r/libqhull_r/*
License: Qhull
  For details, see subprojects/qhull_r/libqhull_r/COPYING.txt

Name: xsf
Files: subprojects/xsf/*
License: BSD-3-Clause AND MIT AND BSD-3-Clause-LBNL AND Apache-2.0 WITH LLVM-exception
  For details, see subprojects/xsf/LICENSE and
  subprojects/xsf/LICENSES_bundled.txt

Name: pyduccfft
Files: scipy/fft/_duccfft/pyduccfft.cxx
License: 3-Clause BSD
  For details, see scipy/fft/_duccfft/LICENSE.md

Name: ducc0
Files: subprojects/duccfft/ducc0/*
License: 3-Clause BSD
  For details, see subprojects/duccfft/LICENSE.md

Name: uarray
Files: scipy/_lib/_uarray/*
License: BSD-3-Clause
  For details, see scipy/_lib/_uarray/LICENSE

Name: ampgo
Files: benchmarks/benchmarks/go_benchmark_functions/*.py
License: MIT
  Functions for testing global optimizers, forked from the AMPGO project,
  https://code.google.com/archive/p/ampgo

Name: pybind11
Files: no source files are included, however pybind11 binary artifacts are
  included with every binary build of SciPy.
License: BSD-3-Clause
  Copyright (c) 2016 Wenzel Jakob <wenzel.jakob@epfl.ch>, All rights reserved.

  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the following conditions are met:

  1. Redistributions of source code must retain the above copyright notice, this
     list of conditions and the following disclaimer.

  2. Redistributions in binary form must reproduce the above copyright notice,
     this list of conditions and the following disclaimer in the documentation
     and/or other materials provided with the distribution.

  3. Neither the name of the copyright holder nor the names of its contributors
     may be used to endorse or promote products derived from this software
     without specific prior written permission.

  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Name: HiGHS
Files: subprojects/highs/*
License: MIT
  For details, see subprojects/highs/LICENSE.txt

Name: Boost
Files: subprojects/boost_math/math/*
License: BSL-1.0
  For details, see subprojects/boost_math/math/LICENSE

Name: Biasedurn
Files: scipy/stats/biasedurn/*
License: BSD-3-Clause
  For details, see scipy/stats/biasedurn/license.txt

Name: UNU.RAN
Files: subprojects/unuran/unuran/*
License: BSD-3-Clause
  For details, see subprojects/unuran/unuran/license.txt

Name: NumPy
Files: scipy/stats/libnpyrandom/[logfactorial.h,logfactorial.c]
License: BSD-3-Clause
  For details, see header inside scipy/stats/libnpyrandom/logfactorial.h
  and scipy/stats/libnpyrandom/logfactorial.c

Name: array-api-compat
Files: subprojects/array_api_compat/array_api_compat/*
License: MIT
  For details, see subprojects/array_api_compat/array_api_compat/LICENSE

Name: array-api-extra
Files: subprojects/array_api_extra/*
License: MIT
  For details, see subprojects/array_api_extra/LICENSE

Name: Tempita
Files: scipy/_build_utils/tempita/*
License: MIT
  For details, see scipy/_build_utils/tempita/LICENSE.txt

Name: Chebfun
Files: scipy/interpolate/[_bary_rational.py, tests/test_bary_rational.py]
License: BSD-3-Clause
  For details, see scipy/interpolate/_bary_rational.py

Name: getLebedevSphere
Files: scipy/integrate/_lebedev.py
License: BSD-2-Clause
  For details, see scipy/integrate/_lebedev.py

Name: prima
Files: subprojects/pyprima/pyprima
License: BSD-3-Clause
  For details, see subprojects/pyprima/pyprima/LICENCE.txt

Name: packaging.version
Files: scipy/_external/packaging_version/*
License: BSD-3-Clause
  For details, see scipy/_external/src/LICENSE.BSD

### OpenBLAS 0.3.31 (scipy.libs/libopenblas.so)
Licence: BSD-3-Clause
Source: https://github.com/OpenMathLib/OpenBLAS/blob/v0.3.31/LICENSE (the version https://github.com/pyodide/pyodide-recipes/blob/314-20260911/packages/libopenblas/meta.yaml pins)

Copyright (c) 2011-2014, The OpenBLAS Project
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   1. Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.

   2. Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in
      the documentation and/or other materials provided with the
      distribution.
   3. Neither the name of the OpenBLAS project nor the names of 
      its contributors may be used to endorse or promote products 
      derived from this software without specific prior written 
      permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

### LAPACK (compiled into OpenBLAS 0.3.31)
Licence: BSD-3-Clause (LAPACK's modified BSD, below)
Source: https://github.com/OpenMathLib/OpenBLAS/blob/v0.3.31/lapack-netlib/LICENSE

Copyright (c) 1992-2023 The University of Tennessee and The University
                        of Tennessee Research Foundation.  All rights
                        reserved.
Copyright (c) 2000-2023 The University of California Berkeley. All
                        rights reserved.
Copyright (c) 2006-2023 The University of Colorado Denver.  All rights
                        reserved.

$COPYRIGHT$

Additional copyrights may follow

$HEADER$

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

- Redistributions of source code must retain the above copyright
  notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
  notice, this list of conditions and the following disclaimer listed
  in this license in the documentation and/or other materials
  provided with the distribution.

- Neither the name of the copyright holders nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

The copyright holders provide no reassurances that the source code
provided does not infringe any patent, copyright, or any other
intellectual property rights of third parties.  The copyright holders
disclaim any liability to any recipient for claims brought against
recipient by any third party for infringement of that parties
intellectual property rights.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

### libf2c from CLAPACK 3.2.1 (linked into scipy.libs/libopenblas.so)
Licence: the AT&T/Lucent notice below
Source: https://www.netlib.org/clapack/clapack.tgz, F2CLIBS/libf2c/Notice (the archive https://github.com/pyodide/pyodide-recipes/blob/314-20260911/packages/libf2c/meta.yaml pins, sha256 checked)

/****************************************************************
Copyright 1990 - 1997 by AT&T, Lucent Technologies and Bellcore.

Permission to use, copy, modify, and distribute this software
and its documentation for any purpose and without fee is hereby
granted, provided that the above copyright notice appear in all
copies and that both that the copyright notice and this
permission notice and warranty disclaimer appear in supporting
documentation, and that the names of AT&T, Bell Laboratories,
Lucent or Bellcore or any of their entities not be used in
advertising or publicity pertaining to distribution of the
software without specific, written prior permission.

AT&T, Lucent and Bellcore disclaim all warranties with regard to
this software, including all implied warranties of
merchantability and fitness.  In no event shall AT&T, Lucent or
Bellcore be liable for any special, indirect or consequential
damages or any damages whatsoever resulting from loss of use,
data or profits, whether in an action of contract, negligence or
other tortious action, arising out of or in connection with the
use or performance of this software.
****************************************************************/
