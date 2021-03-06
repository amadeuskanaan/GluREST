__author__ = 'kanaan' '2014-12-17'
# -*- coding: utf-8 -*-

# based on CPAC038
# see https://github.com/FCP-INDI/C-PAC
import numpy as np
import nibabel as nib
import os
    

def calc_DVARS(rest, mask):
    '''
    Method to calculate DVARS according to (Power, 2012)
    CPAC-0.3.8 implenentation
    '''
    import numpy as np
    import nibabel as nb
    import os

    dvars_out    = os.path.join(os.getcwd(), 'DVARS.npy')
    rest_data    = nb.load(rest).get_data().astype(np.float32)
    mask_data    = nb.load(mask).get_data().astype(np.bool)
    #square of relative intensity value for each voxel across every timepoint
    data         = np.square(np.diff(rest_data, axis = 3))
    #applying mask, getting the data in the brain only
    data         = data[mask_data]
    #square root and mean across all timepoints inside mask
    DVARS        = np.sqrt(np.mean(data, axis=0))

    np.save(dvars_out, DVARS)
    return dvars_out

def return_DVARS(rest, mask):

    rest_data = nib.load(rest).get_data().astype(np.float32)
    mask_data = nib.load(mask).get_data().astype('bool')
    
    #square of relative intensity value for each voxel across
    #every timepoint
    data = np.square(np.diff(rest_data, axis = 3))
    #applying mask, getting the data in the brain only
    data = data[mask_data]
    #square root and mean across all timepoints inside mask
    DVARS = np.sqrt(np.mean(data, axis=0))
    
    return DVARS



def calc_FD_power(motion_pars):
    '''
    Method to calculate FD based on (Power, 2012)
    '''
    import os
    import numpy as np

    fd_out       =  os.path.join(os.getcwd(), 'FD.1D')
    lines        =  open(motion_pars, 'r').readlines()
    rows         = [[float(x) for x in line.split()] for line in lines]
    cols         = np.array([list(col) for col in zip(*rows)])
    translations = np.transpose(np.abs(np.diff(cols[0:3, :])))
    rotations    = np.transpose(np.abs(np.diff(cols[3:6, :])))
    FD_power     = np.sum(translations, axis = 1) + (50*3.141/180)*np.sum(rotations, axis =1)
    #FD is zero for the first time point
    FD_power = np.insert(FD_power, 0, 0)

    np.savetxt(fd_out, FD_power)

    return fd_out


def calc_power_motion_params(subject_id, fd_1d, DVARS, threshold = 0.2):

    '''
    Method to calculate J.D.Power specific parameters used for scrubbing
    Returns csv with various useful motion paramaters
    '''

    import os
    import numpy as np
    from numpy import loadtxt

    out_file     = os.path.join(os.getcwd(), 'motion_power_params.txt')
    f= open(out_file,'w')
    print >>f, "Subject," \
               "FD_μ, " \
               "FD_exclude, " \
               "FD_exclude_%, " \
               "FD_topQuart_μ, " \
               "FD_RMS, " \
               "FD_max, " \
               "DVARS_μ " \

    f.write("%s," % subject_id)

    # calc Mean FD
    data= loadtxt(fd_1d)
    meanFD  = np.mean(data)
    f.write('%.4f,' % meanFD)

    # calc # of frames above FD thresh
    numFD = float(data[data >threshold].size)
    f.write('%.4f,' % numFD)

    # percentage of frames thresholded
    count = np.float(data[data>threshold].size)
    percentFD = (count*100/(len(data)+1))
    f.write('%.4f,' %percentFD)

    # Mean of the top fourth quartile of FD
    quat=int(len(data)/4)
    FDquartile=np.mean(np.sort(data)[::-1][:quat])
    f.write('%.4f,' % FDquartile)

    # RMS of FD
    rmsFD = np.sqrt(np.mean(data))
    f.write('%.4f,' % rmsFD)

    # FD max
    fd_max = np.max(data)
    f.write('%.4f,' % fd_max)

    # mean DVARS
    meanDVARS = np.mean(np.load(DVARS))
    f.write('%.4f,' % meanDVARS)
    f.close()

    return out_file


def calc_frames_excluded(fd_1d, fd_thresh = 0.2, frames_before = 1, frames_after = 2):
    '''
    CPAC-0.3.8 implenentation
    Method to calculate the number of timepoints that would be excluded
    after scrubbing bad frames
    Removes the offending time frame, one before and two after.

    inputs
        fd_1D string
        fd_threshold int
        frames_before
        frames_after
    outputs
        frames_excluded.1D string
    '''

    import os
    import numpy as np
    from numpy import loadtxt

    out_file     = os.path.join(os.getcwd(), 'frames_excluded.1D')
    data         = loadtxt(fd_1d)

    #mask zero timepoint to 0 since no timepoint precedes it, ie. no mean FD val
    data[0] = 0
    extra_indices = []

    indices = [i[0] for i in (np.argwhere(data >= fd_thresh)).tolist()]

    for i in indices:
        #remove succeeding frames
        if i > 0 :
            count = 1
            while count <= frames_before:
                extra_indices.append(i-count)
                count+=1
        #remove following frames
        count = 1
        while count <= frames_after:
            extra_indices.append(i+count)
            count+=1
        indices = list(set(indices) | set(extra_indices))
    indices.sort()

    f = open(out_file, 'a')
    for idx in indices:
        f.write('%s,' % int(idx))
    f.close()

    return out_file


def calc_frames_included(fd_1d, exclude_list, fd_threshold = 0.2):
    '''
    CPAC-0.3.8 implenentation
    Method to calculate the number of timepoints left after scrubbing above a specific FD threshold

    inputs
        fd_1D string
        fd_threshold int
    outputs
        frames_included string
    '''

    import os
    import numpy as np
    from numpy import loadtxt

    out_file = os.path.join(os.getcwd(), 'frames_in.1D')

    data = loadtxt(fd_1d)
    #masking zeroth timepoint value as 0, since the mean displacment value for
    #zeroth timepoint cannot be calculated, as there is no timepoint before it
    data[0] = 0

    indices = [i[0] for i in (np.argwhere(data < fd_threshold)).tolist()]

    indx = []
    f = open(exclude_list, 'r')
    line = f.readline()
    if line:
        line = line.strip(',')
        indx = map(int, line.split(","))
    f.close()
    print indx

    if indx:
        indices = list(set(indices) - set(indx))

    f = open(out_file, 'a')

    for idx in indices:
        f.write('%s,' % int(idx))

    f.close()

    return out_file




