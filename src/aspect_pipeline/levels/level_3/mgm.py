# MGM Python module

import numpy
import pandas
import scipy.optimize
import statsmodels.api
import tabulate
import matplotlib
import matplotlib.pyplot
import os

__wavenumber = 1.0e7
__eps = 0.01


###############################
# Public functions

def absModel(x,cp):
    y = 0.0
    for pv in numpy.array(cp).reshape((-1,3)):
        y = y + pv[0] * numpy.exp(-0.5 * ((_wlwn(x)-pv[1])/pv[2])**2)
    return -y

def bandDepths(res):
    fit1 = res[1]
    fitlin = res[2]
    np = len(fit1)
    if np < 1:
        return None
    
    # Model estimates
    nfit1c = numpy.array([ contModel(_wlwn(wl),fitlin) for wl in fit1[:,1] ])
    nfit1a = numpy.array([ absModel(_wlwn(wl),fit1) for wl in fit1[:,1] ])
    
    # Parameters
    bd = _e2r(nfit1c) - _e2r(nfit1c+nfit1a)
    bw = fit1[:,2] * 2 * numpy.sqrt(2 * numpy.log(2))
    
    return numpy.array([bd, fit1[:,1], bw]).T

def contModel(x,linpar):
    y = 0.0
    lpn = len(linpar)
    for j1 in range(lpn):
        y = y + linpar[j1] * x**j1
    return y


def dataConvert(d):
    d1 = d
    rma = numpy.max(d1[:,1])
    d1[:,1] /= rma
    return numpy.array([[_wlwn(x[0]),_r2e(x[1])] for x in d1])


def fit(d, ip, eps = __eps, contLinDeg = -1, maxRounds = 25):
    nd = len(d)
    np = len(ip)
    # Convert data
    cd = dataConvert(d)
    # Sort initial parameters according to mean
    cp = numpy.array(ip)
    cp = cp[cp[:, 1].argsort()]
    # Define function to be optimized in round 0
    def _minfun(pars):
        ss = 0.0
        for [x,y] in cd:
            ss = ss + (y - absModel(x,pars))**2
        return ss
    parinit = numpy.array(ip).flatten()
    # Do optimization round 0
    # constraints
    # lower bounds, positive
    conlow = numpy.zeros(np*3)
    # one-constraint-per-variable matrix
    conmat = numpy.diag(numpy.ones(np*3))
    for j1 in range(4,np*3,3):
        conmat[j1,j1-3] = -1.
    cons = scipy.optimize.LinearConstraint(conmat,lb=conlow)
    ores = scipy.optimize.minimize(_minfun, parinit, constraints=cons)
    if contLinDeg<0:
        return ores
    
    # Do next optimization rounds
    prevmin = numpy.inf
    curmin = numpy.sqrt(ores.fun/nd)
    j1 = 1
    Xmat = []
    for (wn,val) in cd:
        row = [1.]
        for linpow in range(1,contLinDeg+1):
            row.append(wn**linpow)
        Xmat.append(row)
    Xmat = numpy.array(Xmat)
    contlabs = [ "b"+str(degr) for degr in range(contLinDeg+1)]
    while j1 == 2 or (prevmin - curmin > eps and j1 <= maxRounds):
        # print("")
        # print(f"=== Optimizing round {j1} === ");
        # Linear continuum
        evec = numpy.array([ val - absModel(wn,ores.x) for (wn,val) in cd])
        linres = statsmodels.api.OLS(evec,Xmat).fit()
        # Non-linear MGM
        def _minfun(pars):
            ss = 0.0
            for [x,y] in cd:
                ss = ss + (y - absModel(x,pars) - contModel(x,linres.params))**2
            return ss
            prevmin = 0
        ores = scipy.optimize.minimize(_minfun, ores.x, constraints=cons)
        prevmin = curmin
        curmin = numpy.sqrt(ores.fun/nd)
        # Print progress info
        # print(f"RMS {curmin}, difference to previous {prevmin-curmin}")
        # print("Band parameters")
        xtab = ores.x.reshape((-1,3)).tolist()
        tab = [['','s','mu','sigma']]
        for j2 in range(np):
            tab.append([f"Band {j2}"] + xtab[j2])
        # print(tabulate.tabulate(tab,headers='firstrow'))
        # print("Continuum parameters")
        xtab = [linres.params.tolist(),linres.pvalues.tolist()]
        tab = [['']+contlabs]
        tab.append(['estimate']+linres.params.tolist())
        tab.append(['p-value']+linres.pvalues.tolist())
        # print(tabulate.tabulate(tab,headers='firstrow'))
        j1 = j1+1
    
    return [curmin, ores.x.reshape(-1,3), linres.params, linres.pvalues]


def plot(dat, res, resolution=None):
    if isinstance(res[0],list):
        fit1 = res
        fitlin = []
    else:
        fit1 = res[1]
        fitlin = res[2]
    np = len(fit1)
    rma = numpy.max(dat[:,1])
    # Convert data
    cd = dataConvert(dat)
    # X-axis resolution for the model
    if resolution is None:
        wlreso = dat[1,0]-dat[0,0]
    else:
        wlreso = resolution
    xmi = numpy.min(dat[:,0])
    xma = numpy.max(dat[:,0])
    wnx = [_wlwn(x) for x in numpy.arange(xmi,xma+wlreso,wlreso)]
    
    # Model estimates
    nfit1c = numpy.array([ [wn, contModel(wn,fitlin)] for wn in wnx ])
    nfit1a = numpy.array([ [wn, absModel(wn,fit1)] for wn in wnx ])
    nfit1 = numpy.array([wnx,nfit1c[:,1]+nfit1a[:,1]]).T
    nfitc = numpy.array([ [_wlwn(wn), _e2r(x)] for (wn,x) in nfit1c])
    nfita = numpy.array([ [_wlwn(wn), _e2r(x)] for (wn,x) in nfit1a])
    nfit = numpy.array([ [_wlwn(wn), _e2r(x)] for (wn,x) in nfit1])
    
    # Plot
    cycler = matplotlib.pyplot.cycler(linestyle=['-', '-', '--', '--'],linewidth=[3.0,3.0,1.5,1.5]) + \
        matplotlib.pyplot.rcParams['axes.prop_cycle'][:4]
    plt1 = matplotlib.figure.Figure()
    plt1_ax = plt1.add_subplot()
    plt1_ax.set_prop_cycle(cycler)
    plt1_ax.plot(cd[:,0],cd[:,1],nfit1[:,0],nfit1[:,1],nfit1c[:,0],nfit1c[:,1],nfit1a[:,0],nfit1a[:,1])
    plt1_ax.set_xlabel("Wavenumber (1/cm)")
    plt1_ax.set_ylabel("Log-reflectance, shifted")
    plt1_ax.legend(["data", "fit", "continuum", "bands"])
    plt2 = matplotlib.figure.Figure()
    plt2_ax = plt2.add_subplot()
    plt2_ax.set_prop_cycle(cycler)
    plt2_ax.plot(dat[:,0],dat[:,1],nfit[:,0],nfit[:,1],nfitc[:,0],nfitc[:,1],nfita[:,0],nfita[:,1])
    plt2_ax.set_xlabel("Wavelength (nm)")
    plt2_ax.set_ylabel("Reflectance")
    plt2_ax.legend(["data", "fit", "continuum", "bands"])
    
    return (plt1,plt2)


###############################
# Private functions


def _e2r(x):
    return numpy.exp(x)


def _r2e(x):
    return numpy.log(x)


def _wlwn(x):
    return __wavenumber/x
