'''
Created on 16/11/2016

@author: Alex Ip
'''
import netCDF4
import numpy as np
import math
import os
import re
import tempfile
from scipy.interpolate import griddata
from geophys_utils._crs_utils import get_spatial_ref_from_crs, transform_coords, get_utm_crs

class NetCDFLineUtils(object):
    '''
    NetCDFLineUtils class to do various fiddly things with NetCDF geophysics line data files.
    '''

    def __init__(self, netcdf_dataset):
        '''
        NetCDFLineUtils Constructor
        @parameter netcdf_dataset: netCDF4.Dataset object containing a line dataset
        '''
        self.netcdf_dataset = netcdf_dataset
        self.opendap = (re.match('^http.*', self.netcdf_dataset.filepath()) is not None)
        if self.opendap:
            self.max_bytes = 500000000 # 500MB limit for NCI OPeNDAP
        else:
            self.max_bytes = 8000000000 # 8GB limit for direct netCDF file access
        
        self.crs_variable = netcdf_dataset.variables['crs'] #TODO: Make this more general
        try:
            self.crs = self.crs_variable.spatial_ref
        except:
            self.crs = get_spatial_ref_from_crs(self.crs_variable.epsg_code).ExportToWkt()

        self.point_variables = list([var_name for var_name in self.netcdf_dataset.variables.keys() 
                                     if 'point' in self.netcdf_dataset.variables[var_name].dimensions
                                     and var_name not in ['latitude', 'longitude', 'point', 'fiducial', 'flag_linetype']
                                     ])
        
        # Create local cache for coordinates
        nc_cache_path = os.path.join(tempfile.gettempdir(), re.sub('\W', '_', os.path.splitext(self.netcdf_dataset.filepath())[0] + '.nc'))
        self._nc_cache_dataset = netCDF4.Dataset(nc_cache_path, mode="w", clobber=True, format='NETCDF4')
        
        point_dimension = self.netcdf_dataset.dimensions['point']
        self.point_count = len(point_dimension)
        
        self._nc_cache_dataset.createDimension('point', self.point_count if not point_dimension.isunlimited() else None)
        self._nc_cache_dataset.createDimension('xy', 2)
    
        var_options = {'zlib': False}
        self._nc_cache_dataset.createVariable('xycoords', 
                                      self.netcdf_dataset.variables['longitude'].dtype, 
                                      ('point', 'xy'),
                                      **var_options
                                      )
        self.xycoords = self._nc_cache_dataset.variables['xycoords']

        pieces_required = max(self.xycoords.dtype.itemsize * reduce(lambda x, y: x * y, self.xycoords.shape) / self.max_bytes, 1)
        max_elements = self.point_count / pieces_required

        # Populate xycoords cache
        start_index = 0
        while start_index < self.point_count:
            end_index = min(start_index + max_elements, self.point_count)
            # Pull lat/lon coordinates out of individual lat/lon arrays - note XY order
            xycoords_slice = slice(start_index, end_index)
            self.xycoords[xycoords_slice, 0] = self.netcdf_dataset.variables['longitude'][xycoords_slice]
            self.xycoords[xycoords_slice, 1] = self.netcdf_dataset.variables['latitude'][xycoords_slice]
            start_index += max_elements
 
        # Determine exact spatial bounds
        min_lon = min(self.xycoords[:,0])
        max_lon = max(self.xycoords[:,0])
        min_lat = min(self.xycoords[:,1])
        max_lat = max(self.xycoords[:,1])
        self.bounds = (min_lon, min_lat, max_lon, max_lat)

        
    def __del__(self):
        '''
        NetCDFLineUtils Destructor
        '''
        cache_file_path = self._nc_cache_dataset.filename()
        self._nc_cache_dataset.close()
        os.remove(cache_file_path)
        
    def get_polygon(self):
        '''
        Under construction - do not use except for testing
        '''
        pass
    
    def get_spatial_mask(self, bounds, bounds_crs=None):
        '''
        Return boolean mask of dimension 'point' for all coordinates within specified bounds and CRS
        '''
        if bounds_crs is None:
            coordinates = self.xycoords
        else:
            coordinates = np.array(transform_coords(self.xycoords[...], self.crs, bounds_crs))
            
        return np.logical_and(np.logical_and((bounds[0] <= coordinates[:,0]), (coordinates[:,0] <= bounds[2])), 
                              np.logical_and((bounds[1] <= coordinates[:,1]), (coordinates[:,1] <= bounds[3]))
                              )
            
        
    
    def get_line_masks(self, line_numbers=None):
        '''
        Under construction - do not use except for testing
        '''
        line_number_array = self.netcdf_dataset.variables['line'][...]
        line_start_array = self.netcdf_dataset.variables['_index_line'][...]
        line_end_array = line_start_array + self.netcdf_dataset.variables['_index_count'][...]
        
        # Deal with single line number not in list
        single_line = type(line_numbers) in [int, long]
        if single_line: 
            line_numbers = [line_numbers]
            
        # Return all lines if not specified
        if line_numbers is None:
            line_numbers = line_number_array
            
        line_mask_dict = {}
        for line_number in line_numbers:
            line_index = np.where(line_number_array == line_number)[0]
            
            line_mask = np.zeros((self.point_count,), bool)
            line_mask[line_start_array[line_index]:line_end_array[line_index]] = True
            
            line_mask_dict[line_number] = line_mask

        if single_line: # Return mask not dict
            return line_mask_dict.values()[0]
        else:
            return line_mask_dict
    
    
    def get_lines(self, line_numbers=None, variables=None, bounds=None, bounds_crs=None):
        '''
        Under construction - do not use except for testing
        '''
        # Deal with single line number not in list
        single_line = type(line_numbers) in [int, long]
        if single_line: 
            line_numbers = [line_numbers]

        # Return all lines if not specified
        if line_numbers is None:
            line_numbers = self.netcdf_dataset.variables['line'][...]

        # Allow single variable to be given as a string
        variables = variables or self.point_variables
        single_var = (type(variables) in [str, unicode])
        if single_var:
            variables = [variables]
        
        line_masks = self.get_line_masks(line_numbers=line_numbers)
        
        bounds = bounds or self.bounds
        
        spatial_subset_mask = self.get_spatial_mask(self.get_reprojected_bounds(bounds, bounds_crs, self.crs))
        
        line_dict = {}
        for line_number in line_numbers:
            point_mask = np.logical_and(line_masks[line_number], spatial_subset_mask)
            line_dict[line_number] = {'coordinates': self.xycoords[point_mask]}
            for variable_name in variables:
                line_dict[line_number][variable_name] = self.netcdf_dataset.variables[variable_name][point_mask]
        
        if single_line:
            return line_dict.values()[0]
        else:
            return line_dict
            
            
            
    def get_reprojected_bounds(self, bounds, from_crs, to_crs):
        '''
        Function to take a bounding box specified in one CRS and return its smallest containing bounding box in a new CRS
        @parameter bounds: bounding box specified as tuple(xmin, ymin, xmax, ymax) in CRS from_crs
        @parameter from_crs: CRS from which to transform bounds
        @parameter to_crs: CRS to which to transform bounds
        
        @return reprojected_bounding_box: bounding box specified as tuple(xmin, ymin, xmax, ymax) in CRS to_crs
        '''
        if (to_crs is None) or (from_crs is None) or (to_crs == from_crs):
            return bounds
        
        # Need to look at all four bounding box corners, not just LL & UR
        original_bounding_box =((bounds[0], bounds[1]), (bounds[2], bounds[1]), (bounds[2], bounds[3]), (bounds[0], bounds[3]))
        reprojected_bounding_box = np.array(transform_coords(original_bounding_box, from_crs, to_crs))
        
        return [min(reprojected_bounding_box[:,0]), min(reprojected_bounding_box[:,1]), max(reprojected_bounding_box[:,0]), max(reprojected_bounding_box[:,1])]
            
            
    def grid_points(self, grid_resolution, 
                    variables=None, 
                    native_grid_bounds=None, 
                    reprojected_grid_bounds=None, 
                    resampling_method='linear', 
                    grid_crs=None, 
                    point_step=1):
        '''
        Function to grid points in a specified bounding rectangle to a regular grid of the specified resolution and crs
        @parameter grid_resolution: cell size of regular grid in grid CRS units
        @parameter variables: Single variable name string or list of multiple variable name strings. Defaults to all point variables
        @parameter native_grid_bounds: Spatial bounding box of area to grid in native coordinates 
        @parameter reprojected_grid_bounds: Spatial bounding box of area to grid in grid coordinates
        @parameter resampling_method: Resampling method for gridding. 'linear' (default), 'nearest' or 'cubic'. 
        See https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.griddata.html 
        @parameter grid_crs: WKT for grid coordinate reference system. Defaults to native CRS
        @parameter point_step: Sampling spacing for points. 1 (default) means every point, 2 means every second point, etc.
        
        @return grids: dict of grid arrays keyed by variable name if parameter 'variables' value was a list, or
        a single grid array if 'variable' parameter value was a string
        @return crs: WKT for grid coordinate reference system.
        @return geotransform: GDAL GeoTransform for grid
        '''
        assert not (native_grid_bounds and reprojected_grid_bounds), 'Either native_grid_bounds or reprojected_grid_bounds can be provided, but not both'
        # Grid all data variables if not specified
        variables = variables or self.point_variables

        # Allow single variable to be given as a string
        single_var = (type(variables) in [str, unicode])
        if single_var:
            variables = [variables]
        
        if native_grid_bounds:
            reprojected_grid_bounds = self.get_reprojected_bounds(native_grid_bounds, self.crs, grid_crs)
        elif reprojected_grid_bounds:
            native_grid_bounds = self.get_reprojected_bounds(reprojected_grid_bounds, grid_crs, self.crs)
        else: # No reprojection required
            native_grid_bounds = self.bounds
            reprojected_grid_bounds = self.bounds

        # Determine spatial grid bounds rounded out to nearest GRID_RESOLUTION multiple
        pixel_centre_bounds = (round(math.floor(reprojected_grid_bounds[0] / grid_resolution) * grid_resolution, 6),
                       round(math.floor(reprojected_grid_bounds[1] / grid_resolution) * grid_resolution, 6),
                       round(math.floor(reprojected_grid_bounds[2] / grid_resolution - 1.0) * grid_resolution + grid_resolution, 6),
                       round(math.floor(reprojected_grid_bounds[3] / grid_resolution - 1.0) * grid_resolution + grid_resolution, 6)
                       )
        
        grid_size = [pixel_centre_bounds[dim_index+2] - pixel_centre_bounds[dim_index] for dim_index in range(2)]

        # Extend area for points an arbitrary 4% out beyond grid extents for nice interpolation at edges
        expanded_grid_bounds = [pixel_centre_bounds[0]-grid_size[0]/50.0,
                                pixel_centre_bounds[1]-grid_size[0]/50.0,
                                pixel_centre_bounds[2]+grid_size[1]/50.0,
                                pixel_centre_bounds[3]+grid_size[1]/50.0
                                ]

        spatial_subset_mask = self.get_spatial_mask(self.get_reprojected_bounds(expanded_grid_bounds, grid_crs, self.crs))
        
        # Create grids of Y and X values. Note YX ordering and inverted Y
        # Note GRID_RESOLUTION/2.0 fudge to avoid truncation due to rounding error
        grid_y, grid_x = np.mgrid[pixel_centre_bounds[3]:pixel_centre_bounds[1]-grid_resolution/2.0:-grid_resolution, 
                                 pixel_centre_bounds[0]:pixel_centre_bounds[2]+grid_resolution/2.0:grid_resolution]

        # Skip points to reduce memory requirements
        #TODO: Implement function which grids spatial subsets.
        point_subset_mask = np.zeros(shape= self.netcdf_dataset.variables['point'].shape, dtype=bool)
        point_subset_mask[0:-1:point_step] = True
        point_subset_mask = np.logical_and(spatial_subset_mask, point_subset_mask)
        
        coordinates = self.xycoords[...][point_subset_mask]
        # Reproject coordinates if required
        if grid_crs is not None:
            # N.B: Be careful about XY vs YX coordinate order         
            coordinates = np.array(transform_coords(coordinates[...], self.crs, grid_crs))

        # Interpolate required values to the grid - Note YX ordering for image
        grids = {}
        for variable in [self.netcdf_dataset.variables[var_name] for var_name in variables]:
            grids[variable.name] = griddata(coordinates[:,::-1],
                                  variable[...][point_subset_mask], #TODO: Check why this is faster than direct indexing
                                  (grid_y, grid_x), 
                                  method=resampling_method)

        if single_var:
            grids = grids.values()[0]
            
        #  crs:GeoTransform = "109.1002342895272 0.00833333 0 -9.354948067227777 0 -0.00833333 "
        geotransform = [pixel_centre_bounds[0]-grid_resolution/2.0,
                        grid_resolution,
                        0,
                        pixel_centre_bounds[3]+grid_resolution/2.0,
                        0,
                        -grid_resolution
                        ] 

        return grids, (grid_crs or self.crs), geotransform
    
    
    def utm_grid_points(self, utm_grid_resolution, variables=None, native_grid_bounds=None, resampling_method='linear', point_step=1):
        '''
        Function to grid points in a specified native bounding rectangle to a regular grid of the specified resolution in its local UTM CRS
        @parameter grid_resolution: cell size of regular grid in metres (UTM units)
        @parameter variables: Single variable name string or list of multiple variable name strings. Defaults to all point variables
        @parameter native_grid_bounds: Spatial bounding box of area to grid in native coordinates 
        @parameter resampling_method: Resampling method for gridding. 'linear' (default), 'nearest' or 'cubic'. 
        See https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.griddata.html 
        @parameter grid_crs: WKT for grid coordinate reference system. Defaults to native CRS
        @parameter point_step: Sampling spacing for points. 1 (default) means every point, 2 means every second point, etc.
        
        @return grids: dict of grid arrays keyed by variable name if parameter 'variables' value was a list, or
        a single grid array if 'variable' parameter value was a string
        @return crs: WKT for grid coordinate reference system (i.e. local UTM zone)
        @return geotransform: GDAL GeoTransform for grid
        '''
        native_grid_bounds = native_grid_bounds or self.bounds
        
        native_centre_coords = [(native_grid_bounds[dim_index] + native_grid_bounds[dim_index+2]) / 2.0 for dim_index in range(2)]
        utm_crs = get_utm_crs(native_centre_coords, self.crs)
        
        return self.grid_points(grid_resolution=utm_grid_resolution, 
                                variables=variables,
                                native_grid_bounds=native_grid_bounds, 
                                resampling_method=resampling_method, 
                                grid_crs=utm_crs, 
                                point_step=point_step
                                )

