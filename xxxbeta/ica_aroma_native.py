import os
import argparse
import commands
import shutil
from nipype.pipeline.engine import Workflow, Node
import nipype.interfaces.utility as util
from nipype.interfaces.base import CommandLine
import os


# Forked from https://github.com/rhr-pruim
# Authour:  Pruim, R.H.R
#
# References:
#
#       1. Pruim, R.H.R., Mennes, M., van Rooij, D., Llera Arenas, A., Buitelaar, J.K.,
#          Beckmann, C.F., 2014. ICA-AROMA: A robust ICA-based strategy for removing
#          motion artifacts from fMRI data. Neuroimage, 2015
#       2. Pruim, R.H.R., Mennes, M., Buitelaar, J.K., Beckmann, C.F., 2014. Evaluation of
#          ICA-AROMA and alternative strategies for motion artifact removal in resting-state
#          fMRI. Neuroimage, 2015
# ICA-AROMA (i.e ICA-based Automatic Removal Of Motion Artifacts) attempts to
# identify and remove motion artifacts from fMRI data. To that end it exploits
# Independent Component Analysis (ICA) to decompose the data into a set of independent
# components. Subsequently, ICA-AROMA automatically identifies which of these
# components are related to head motion, by using four robust and standardized features.
# The identified components are then removed from the data through linear regression as
# implemented in fsl_regfilt. ICA-AROMA has to be applied after spatial smoothing, but
# prior to temporal filtering within the typical fMRI preprocessing pipeline. Two
# manuscripts provide a detailed description and evaluation of ICA-AROMA:
#
#


# ica_aroma related functions below..... see the ene of the this script for a nipype workflow




fslDir = '/usr/share/fsl/5.0/'
func   = '/SCR2/tmp/ICA_AROMA/func2mni_preproc.nii'
mask   = '/SCR2/tmp/ICA_AROMA/MNI152_T1_2mm_brain_mask.nii.gz'
outdir = '/SCR2/tmp/ICA_AROMA/'
mc     = '/SCR2/tmp/ICA_AROMA/moco.par'



def ica_aroma_denoise(fslDir, inFile, mask, dim, TR, mc, denType):
	import os
	
	def runICA(fslDir, inFile, outDir, mask, dim, TR):
		""" This function runs MELODIC and merges the mixture modeled thresholded ICs into a single 4D nifti file

		Parameters
		---------------------------------------------------------------------------------
		fslDir:		Full path of the bin-directory of FSL
		inFile:		Full path to the fMRI data file (nii.gz) on which MELODIC should be run
		outDir:		Full path of the output directory
		melDirIn:	Full path of the MELODIC directory in case it has been run before, otherwise define empty string
		mask:		Full path of the mask to be applied during MELODIC
		dim:		Dimensionality of ICA
		TR:		TR (in seconds) of the fMRI data

		Output (within the requested output directory)
		---------------------------------------------------------------------------------
		melodic.ica		MELODIC directory
		melodic_IC_thr.nii.gz	merged file containing the mixture modeling thresholded Z-statistical maps located in melodic.ica/stats/ """

		# Import needed modules
		import os
		import commands

		# Define the 'new' MELODIC directory and predefine some associated files
		melDir = os.path.join(outDir,'melodic.ica')
		melIC = os.path.join(melDir,'melodic_IC.nii.gz')
		melICmix = os.path.join(melDir,'melodic_mix')
		melICthr = os.path.join(outDir,'melodic_IC_thr.nii.gz')

		print '  -  Run Melodic - .'

		# Run MELODIC
		os.system(' '.join(['melodic',
			'--in=' + inFile,
			'--outdir=' + melDir,
			'--mask=' + mask,
			'--dim=' + str(dim),
			'--Ostats --nobet --mmthresh=0.5 --report',
			'--tr=' + str(TR)]))

		# Get number of components
		cmd = ' '.join(['fslinfo',
			melIC,
			'| grep dim4 | head -n1 | awk \'{print $2}\''])
		nrICs=int(float(commands.getoutput(cmd)))

		# Merge mixture modeled thresholded spatial maps. Note! In case that mixture modeling did not converge, the file will contain two spatial maps. The latter being the results from a simple null hypothesis test. In that case, this map will have to be used (first one will be empty).
		for i in range(1,nrICs+1):
			# Define thresholded zstat-map file
			zTemp = os.path.join(melDir,'stats','thresh_zstat' + str(i) + '.nii.gz')
			cmd = ' '.join(['fslinfo',
				zTemp,
				'| grep dim4 | head -n1 | awk \'{print $2}\''])
			lenIC=int(float(commands.getoutput(cmd)))

			# Define zeropad for this IC-number and new zstat file
			cmd = ' '.join(['zeropad',
				str(i),
				'4'])
			ICnum=commands.getoutput(cmd)
			zstat = os.path.join(outDir,'thr_zstat' + ICnum)

			# Extract last spatial map within the thresh_zstat file
			os.system(' '.join(['fslroi',
				zTemp,		# input
				zstat,		# output
				str(lenIC-1),	# first frame
				'1']))		# number of frames

		# Merge and subsequently remove all mixture modeled Z-maps within the output directory
		os.system(' '.join(['fslmerge',
			'-t',						# concatenate in time
			melICthr,					# output
			os.path.join(outDir,'thr_zstat????.nii.gz')]))	# inputs

		os.system('rm ' + os.path.join(outDir,'thr_zstat????.nii.gz'))

		# Apply the mask to the merged file (in case a melodic-directory was predefined and run with a different mask)
		os.system(' '.join(['fslmaths',
			melICthr,
			'-mas ' + mask,
			melICthr]))

	def feature_time_series(melmix, mc):
		""" This function extracts the maximum RP correlation feature scores. It determines the maximum robust correlation of each component time-series with a model of 72 realigment parameters.

		Parameters
		---------------------------------------------------------------------------------
		melmix:		Full path of the melodic_mix text file
		mc:		    Full path of the text file containing the realignment parameters

		Returns
		---------------------------------------------------------------------------------
		maxRPcorr:	Array of the maximum RP correlation feature scores for the components of the melodic_mix file"""

		# Import required modules
		import numpy as np
		import random

		# Read melodic mix file (IC time-series), subsequently define a set of squared time-series
		mix = np.loadtxt(melmix)
		mixsq = np.power(mix,2)

		# Read motion parameter file
		RP6 = np.loadtxt(mc)

		# Determine the derivatives of the RPs (add zeros at time-point zero)
		RP6_der = np.array(RP6[range(1,RP6.shape[0]),:] - RP6[range(0,RP6.shape[0]-1),:])
		RP6_der = np.concatenate((np.zeros((1,6)),RP6_der),axis=0)

		# Create an RP-model including the RPs and its derivatives
		RP12 = np.concatenate((RP6,RP6_der),axis=1)

		# Add the squared RP-terms to the model
		RP24 = np.concatenate((RP12,np.power(RP12,2)),axis=1)

		# Derive shifted versions of the RP_model (1 frame for and backwards)
		RP24_1fw = np.concatenate((np.zeros((1,24)),np.array(RP24[range(0,RP24.shape[0]-1),:])),axis=0)
		RP24_1bw = np.concatenate((np.array(RP24[range(1,RP24.shape[0]),:]),np.zeros((1,24))),axis=0)

		# Combine the original and shifted mot_pars into a single model
		RP_model = np.concatenate((RP24,RP24_1fw,RP24_1bw),axis=1)

		# Define the column indices of respectively the squared or non-squared terms
		idx_nonsq = np.array(np.concatenate((range(0,12), range(24,36), range(48,60)),axis=0))
		idx_sq = np.array(np.concatenate((range(12,24), range(36,48), range(60,72)),axis=0))

		# Determine the maximum correlation between RPs and IC time-series
		nSplits=int(1000)
		maxTC = np.zeros((nSplits,mix.shape[1]))
		for i in range(0,nSplits):
			# Get a random set of 90% of the dataset and get associated RP model and IC time-series matrices
			idx = np.array(random.sample(range(0,mix.shape[0]),int(round(0.9*mix.shape[0]))))
			RP_model_temp = RP_model[idx,:]
			mix_temp = mix[idx,:]
			mixsq_temp = mixsq[idx,:]

			# Calculate correlation between non-squared RP/IC time-series
			RP_model_nonsq = RP_model_temp[:,idx_nonsq]
			cor_nonsq = np.array(np.zeros((mix_temp.shape[1],RP_model_nonsq.shape[1])))
			for j in range(0,mix_temp.shape[1]):
				for k in range(0,RP_model_nonsq.shape[1]):
					cor_temp = np.corrcoef(mix_temp[:,j],RP_model_nonsq[:,k])
					cor_nonsq[j,k] = cor_temp[0,1]

			# Calculate correlation between squared RP/IC time-series
			RP_model_sq = RP_model_temp[:,idx_sq]
			cor_sq = np.array(np.zeros((mix_temp.shape[1],RP_model_sq.shape[1])))
			for j in range(0,mixsq_temp.shape[1]):
				for k in range(0,RP_model_sq.shape[1]):
					cor_temp = np.corrcoef(mixsq_temp[:,j],RP_model_sq[:,k])
					cor_sq[j,k] = cor_temp[0,1]

			# Combine the squared an non-squared correlation matrices
			corMatrix = np.concatenate((cor_sq,cor_nonsq),axis=1)

			# Get maximum temporal correlation for every IC
			# maxTC[i,:]=corMatrix.max(axis=1) 		  #v0.2
			corMatrixAbs = np.abs(corMatrix)          #v0.2
			maxTC[i,:] = corMatrixAbs.max(axis=1)     #v0.2


		# Get the mean maximum correlation over all random splits
		maxRPcorr = maxTC.mean(axis=0)

		# Return the feature score
		return maxRPcorr

	def feature_frequency(melFTmix, TR):
		""" This function extracts the high-frequency content feature scores. It determines the frequency, as fraction of the Nyquist frequency, at which the higher and lower frequencies explain half of the total power between 0.01Hz and Nyquist.

		Parameters
		---------------------------------------------------------------------------------
		melFTmix:	Full path of the melodic_FTmix text file
		TR:		TR (in seconds) of the fMRI data (float)

		Returns
		---------------------------------------------------------------------------------
		HFC:		Array of the HFC ('High-frequency content') feature scores for the components of the melodic_FTmix file"""

		# Import required modules
		import numpy as np

		# Determine sample frequency
		Fs = 1/TR

		# Determine Nyquist-frequency
		Ny = Fs/2

		# Load melodic_FTmix file
		FT=np.loadtxt(melFTmix)

		# Determine which frequencies are associated with every row in the melodic_FTmix file  (assuming the rows range from 0Hz to Nyquist)
		#step = Ny / FT.shape[0]      V0.2
		# f = np.arange(step,Ny,step) V0.2
		f = Ny*(np.array(range(1,FT.shape[0]+1)))/(FT.shape[0]) #V0.3

		# Only include frequencies higher than 0.01Hz
		fincl = np.squeeze(np.array(np.where( f > 0.01 )))
		FT=FT[fincl,:]
		f=f[fincl]

		# Set frequency range to [0-1]
		f_norm = (f-0.01)/(Ny-0.01);

		# For every IC; get the cumulative sum as a fraction of the total sum
		fcumsum_fract = np.cumsum(FT,axis=0)/ np.sum(FT,axis=0)

		# Determine the index of the frequency with the fractional cumulative sum closest to 0.5
		idx_cutoff=np.argmin(np.abs(fcumsum_fract-0.5),axis=0)

		# Now get the fractions associated with those indices index, these are the final feature scores
		HFC = f_norm[idx_cutoff]

		# Return feature score
		return HFC

	def feature_spatial(fslDir, tempDir, aromaDir, melIC):
		""" This function extracts the spatial feature scores. For each IC it determines the fraction of the mixture modeled thresholded Z-maps respecitvely located within the CSF or at the brain edges, using predefined standardized masks.

		Parameters
		---------------------------------------------------------------------------------
		fslDir:		Full path of the bin-directory of FSL
		tempDir:	Full path of a directory where temporary files can be stored (called 'temp_IC.nii.gz')
		aromaDir:	Full path of the ICA-AROMA directory, containing the mask-files (mask_edge.nii.gz, mask_csf.nii.gz & mask_out.nii.gz)
		melIC:		Full path of the nii.gz file containing mixture-modeled threholded (p>0.5) Z-maps, registered to the MNI152 2mm template

		Returns
		---------------------------------------------------------------------------------
		edgeFract:	Array of the edge fraction feature scores for the components of the melIC file
		csfFract:	Array of the CSF fraction feature scores for the components of the melIC file"""

		# Import required modules
		import numpy as np
		import os
		import commands

		# Get the number of ICs
		numICs = int(commands.getoutput('fslinfo %s | grep dim4 | head -n1 | awk \'{print $2}\'' %melIC ))

		# Loop over ICs
		edgeFract=np.zeros(numICs)
		csfFract=np.zeros(numICs)
		for i in range(0,numICs):
			# Define temporary IC-file
			tempIC = os.path.join(tempDir,'temp_IC.nii.gz')

			# Extract IC from the merged melodic_IC_thr2MNI2mm file
			os.system(' '.join(['fslroi',
				melIC,
				tempIC,
				str(i),
				'1']))

			# Change to absolute Z-values
			os.system(' '.join(['fslmaths',
				tempIC,
				'-abs',
				tempIC]))

			# Get sum of Z-values within the total Z-map (calculate via the mean and number of non-zero voxels)
			totVox = int(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-V | awk \'{print $1}\''])))

			if not (totVox == 0):
				totMean = float(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-M'])))
			else:
				print '     - The spatial map of component ' + str(i+1) + ' is empty. Please check!'
				totMean = 0

			totSum = totMean * totVox

			# Get sum of Z-values of the voxels located within the CSF (calculate via the mean and number of non-zero voxels)
			csfVox = int(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_csf.nii.gz',
								'-V | awk \'{print $1}\''])))

			if not (csfVox == 0):
				csfMean = float(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_csf.nii.gz',
								'-M'])))
			else:
				csfMean = 0

			csfSum = csfMean * csfVox

			# Get sum of Z-values of the voxels located within the Edge (calculate via the mean and number of non-zero voxels)
			edgeVox = int(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_edge.nii.gz',
								'-V | awk \'{print $1}\''])))
			if not (edgeVox == 0):
				edgeMean = float(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_edge.nii.gz',
								'-M'])))
			else:
				edgeMean = 0

			edgeSum = edgeMean * edgeVox

			# Get sum of Z-values of the voxels located outside the brain (calculate via the mean and number of non-zero voxels)
			outVox = int(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_out.nii.gz',
								'-V | awk \'{print $1}\''])))
			if not (outVox == 0):
				outMean = float(commands.getoutput(' '.join(['fslstats',
								tempIC,
								'-k /scr/sambesi1/workspace/Projects/GluREST/denoise/mask_out.nii.gz',
								'-M'])))
			else:
				outMean = 0

			outSum = outMean * outVox

			# Determine edge and CSF fraction
			if not (totSum == 0):
				edgeFract[i] = (outSum + edgeSum)/(totSum - csfSum)
				csfFract[i] = csfSum / totSum
			else:
				edgeFract[i]=0
				csfFract[i]=0

		# Remove the temporary IC-file
		os.remove(tempIC)

		# Return feature scores
		return edgeFract, csfFract

	def classification(outDir, maxRPcorr, edgeFract, HFC, csfFract):
		""" This function classifies a set of components into motion and non-motion components based on four features; maximum RP correlation, high-frequency content, edge-fraction and CSF-fraction

		Parameters
		---------------------------------------------------------------------------------
		outDir:		Full path of the output directory
		maxRPcorr:	Array of the 'maximum RP correlation' feature scores of the components
		edgeFract:	Array of the 'edge fraction' feature scores of the components
		HFC:		Array of the 'high-frequency content' feature scores of the components
		csfFract:	Array of the 'CSF fraction' feature scores of the components

		Return
		---------------------------------------------------------------------------------
		motionICs	Array containing the indices of the components identified as motion components

		Output (within the requested output directory)
		---------------------------------------------------------------------------------
		classified_motion_ICs.txt	A text file containing the indices of the components identified as motion components """

		# Import required modules
		import numpy as np
		import os
		import commands

		# Classify the ICs as motion or non-motion

		# Define criteria needed for classification (thresholds and hyperplane-parameters)
		thr_csf = 0.10
		thr_HFC = 0.35
		hyp = np.array([-19.9751070082159, 9.95127547670627, 24.8333160239175])

		# Project edge & maxRPcorr feature scores to new 1D space
		x = np.array([maxRPcorr, edgeFract])
		proj = hyp[0] + np.dot(x.T,hyp[1:])

		# Classify the ICs
		motionICs = np.squeeze(np.array(np.where((proj > 0) + (csfFract > thr_csf) + (HFC > thr_HFC))))

		# Put the feature scores in a text file
		np.savetxt(os.path.join(outDir,'feature_scores.txt'),np.vstack((maxRPcorr,edgeFract,HFC,csfFract)).T)

		# Put the indices of motion-classified ICs in a text file
		txt = open(os.path.join(outDir,'classified_motion_ICs.txt'),'w')
		if len(motionICs) != 0:
			txt.write(','.join(['%.0f' % num for num in (motionICs+1)]))
		txt.close()

		# Create a summary overview of the classification
		txt = open(os.path.join(outDir,'classification_overview.txt'),'w')
		txt.write('IC' + '\t' +  'Motion/noise' + '\t' +  'maximum RP correlation' + '\t' +  'Edge-fraction' + '\t\t' +  'High-frequency content' + '\t' + 'CSF-fraction')
		txt.write('\n')
		for i in range(0,len(csfFract)):
			if (proj[i] > 0) or (csfFract[i] > thr_csf) or (HFC[i] > thr_HFC):
				classif="True"
			else:
				classif="False"
			txt.write('%.0f\t%s\t\t%.2f\t\t\t%.2f\t\t\t%.2f\t\t\t%.2f\n' % (i+1, classif, maxRPcorr[i], edgeFract[i], HFC[i], csfFract[i]))
		txt.close()

		return motionICs

	def denoising(fslDir, inFile, outDir, melmix, denType, denIdx):
		""" This function classifies the ICs based on the four features; maximum RP correlation, high-frequency content, edge-fraction and CSF-fraction

		Parameters
		---------------------------------------------------------------------------------
		fslDir:		Full path of the bin-directory of FSL
		inFile:		Full path to the data file (nii.gz) which has to be denoised
		outDir:		Full path of the output directory
		melmix:		Full path of the melodic_mix text file
		denType:	Type of requested denoising ('aggr': aggressive, 'nonaggr': non-aggressive, 'both': both aggressive and non-aggressive
		denIdx:		Indices of the components that should be regressed out

		Output (within the requested output directory)
		---------------------------------------------------------------------------------
		denoised_func_data_<denType>.nii.gz:		A nii.gz file of the denoised fMRI data"""

		# Import required modules
		import os
		import numpy as np

		# Check if denoising is needed (i.e. are there components classified as motion)
		check = len(denIdx) > 0

		if check==1:
			# Put IC indices into a char array
			#denIdxStr = np.char.mod('%i',denIdx)
			denIdxStr = np.char.mod('%i',(denIdx+1))

			# Non-aggressive denoising of the data using fsl_regfilt (partial regression), if requested
			if (denType == 'nonaggr') or (denType == 'both'):
				os.system(' '.join(['fsl_regfilt',
					'--in=' + inFile,
					'--design=' + melmix,
					'--filter="' + ','.join(denIdxStr) + '"',
					'--out=' + os.path.join(outDir,'denoised_func_data_nonaggr.nii.gz')]))

			# Aggressive denoising of the data using fsl_regfilt (full regression)
			if (denType == 'aggr') or (denType == 'both'):
				os.system(' '.join(['fsl_regfilt',
					'--in=' + inFile,
					'--design=' + melmix,
					'--filter="' + ','.join(denIdxStr) + '"',
					'--out=' + os.path.join(outDir,'denoised_func_data_aggr.nii.gz'),
					'-a']))
		else:
			print "  - None of the components was classified as motion, so no denoising is applied (a symbolic link to the input file will be created)."
			if (denType == 'nonaggr') or (denType == 'both'):
				os.symlink(inFile,os.path.join(outDir,'denoised_func_data_nonaggr.nii.gz'))
			if (denType == 'aggr') or (denType == 'both'):
				os.symlink(inFile,os.path.join(outDir,'denoised_func_data_aggr.nii.gz'))


	# Change to script directory
	outDir = os.curdir

	print 'Step 1) MELODIC'
	runICA(fslDir, inFile, outDir, mask, dim, TR)

	print 'Step 2) Automatic classification of the components'

	print '  - extracting the CSF & Edge fraction features'
	melIC_MNI =  os.path.join(outDir,'melodic_IC_thr.nii.gz')
	edgeFract, csfFract = feature_spatial(fslDir, outDir, outDir, melIC_MNI)

	print '  - extracting the Maximum RP correlation feature'
	melmix = os.path.join(outDir,'melodic.ica','melodic_mix')
	maxRPcorr = feature_time_series(melmix, mc)

	print '  - extracting the High-frequency content feature'
	melFTmix = os.path.join(outDir,'melodic.ica','melodic_FTmix')
	HFC = feature_frequency(melFTmix, TR)

	print '  - classification'
	motionICs = classification(outDir, maxRPcorr, edgeFract, HFC, csfFract)

	print 'Step 3) Data denoising'
	# dentype:
	#   'aggr': aggressive,
	#   'nonaggr': non-aggressive,
	#   'both': both aggressive and non-aggressive

	denoising(fslDir, inFile, outDir, melmix, denType, motionICs)

	# Revert to old directory
	
	denoised = os.path.join(os.getcwd(), 'denoised_func_data_nonaggr.nii.gz')

	return denoised

def gICA_AROMA():

	flow  = Workflow('denoise_ica_aroma')

	inputnode  = Node(util.IdentityInterface(fields=['fslDir', 'inFile', 'mask', 'dim', 'TR', 'mc', 'denType']),
					 name = 'inputnode')

	outputnode = Node(util.IdentityInterface(fields=['denoised']),
					 name = 'outputnode')

	aroma = Node(util.Function(input_names   = ['fslDir', 'inFile',  'mask',
											   'dim', 'TR', 'mc', 'denType'],
							   output_names  =['denoised'],
							   function      =ica_aroma_denoise),
							   name ='ICA_AROMA')

	flow.connect(inputnode,        'fslDir',   aroma,     'fslDir'      )
	flow.connect(inputnode,        'inFile',   aroma,     'inFile'      )
	flow.connect(inputnode,        'mask',     aroma,     'mask'        )
	flow.connect(inputnode,        'dim',      aroma,     'dim'         )
	flow.connect(inputnode,        'TR',       aroma,     'TR'          )
	flow.connect(inputnode,        'mc',       aroma,     'mc'          )
	flow.connect(inputnode,        'denType',  aroma,     'denType'     )
	flow.connect(aroma,            'denoised', outputnode,'denoised'  )

	return flow


	# create_flow = create_ica_aroma_workflow()
	# create_flow.inputs.inputnode.fslDir = '/usr/share/fsl/5.0/'
	# create_flow.inputs.inputnode.inFile = '/SCR2/tmp/ICA_AROMA/func2mni_preproc.nii'
	# create_flow.inputs.inputnode.mask   = '/SCR2/tmp/ICA_AROMA/MNI152_T1_2mm_brain_mask.nii.gz'
	# create_flow.inputs.inputnode.dim    = 0
	# create_flow.inputs.inputnode.TR     = 1.4
	# create_flow.inputs.inputnode.mc     = '/SCR2/tmp/ICA_AROMA/moco.par'
	# create_flow.inputs.inputnode.denType= 'aggr'
	# create_flow.run()
