cmake_minimum_required(VERSION 3.16)

project(installer_wizard LANGUAGES CXX)
set(project_type python_module_plugin)
set(enable_warnings OFF)

if(DEFINED DEPENDENCIES_DIR)
    include(${DEPENDENCIES_DIR}/modorganizer_super/cmake_common/project.cmake)
else()
	include(../cmake_common/project.cmake)
endif()

add_subdirectory(src)
