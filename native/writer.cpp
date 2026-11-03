#include <osg/Geode>
#include <osg/Geometry>
#include <osg/Texture2D>
#include <osg/PagedLOD>
#include <osg/AlphaFunc>
#include <osg/BlendFunc>
#include <osg/ComputeBoundsVisitor>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgDB/Registry>
#include <osgDB/Options>
#include <fstream>
#include <iostream>
#include <filesystem>
#include <limits>
#include "json.hpp"
using json=nlohmann::json;
namespace fs=std::filesystem;

template<class T> void read_array(std::ifstream& f, T* data, size_t count) {
    if(!f.read(reinterpret_cast<char*>(data), sizeof(T)*count)) throw std::runtime_error("Truncated geometry buffer");
}
osg::Vec3 center(const json& j) {auto c=j.value("center",std::vector<double>{0,0,0});return osg::Vec3(c[0],c[1],c[2]);}
osg::ref_ptr<osg::PagedLOD> reference(const json& j) {
    auto n=new osg::PagedLOD;
    n->setCenterMode(osg::LOD::USER_DEFINED_CENTER);n->setCenter(center(j));n->setRadius(j.value("radius",1.0));
    n->setFileName(0,j.at("path").get<std::string>());n->setRange(0,0,std::numeric_limits<float>::max());
    return n;
}

struct Rebase:osg::NodeVisitor {
    std::string prefix;
    Rebase(std::string p):NodeVisitor(TRAVERSE_ALL_CHILDREN),prefix(p){}
    void apply(osg::PagedLOD& n)override {
        n.setDatabasePath("");
        for(unsigned i=0;i<n.getNumFileNames();i++)if(!n.getFileName(i).empty())
            n.setFileName(i,(fs::path(prefix)/n.getFileName(i)).lexically_normal().generic_string());
        traverse(n);
    }
};

osg::ref_ptr<osg::Node> create(const json& job) {
    auto geo=new osg::Geode;
    osg::ref_ptr<osg::Geode> geometry=geo;
    if(job.contains("buffer")) {
        std::ifstream f(fs::u8path(job["buffer"].get<std::string>()),std::ios::binary);
        if(!f)throw std::runtime_error("Cannot open geometry buffer");
        for(auto& p:job["primitives"]) {
            f.seekg(p["offset"].get<uint64_t>());
            auto g=new osg::Geometry;
            uint32_t nv=p["vertices"],ni=p["indices"];
            auto xyz=new osg::Vec3Array(nv);read_array(f,&(*xyz)[0],nv);g->setVertexArray(xyz);
            if(p["uv"].get<bool>()) {auto uv=new osg::Vec2Array(nv);read_array(f,&(*uv)[0],nv);g->setTexCoordArray(0,uv);}
            if(p["normals"].get<bool>()) {auto n=new osg::Vec3Array(nv);read_array(f,&(*n)[0],nv);g->setNormalArray(n,osg::Array::BIND_PER_VERTEX);}
            auto idx=new osg::DrawElementsUInt(GL_TRIANGLES,ni);read_array(f,&(*idx)[0],ni);g->addPrimitiveSet(idx);
            auto colors=new osg::Vec4Array;auto c=p["color"];colors->push_back(osg::Vec4(c[0],c[1],c[2],c[3]));g->setColorArray(colors,osg::Array::BIND_OVERALL);
            auto state=g->getOrCreateStateSet();state->setMode(GL_LIGHTING,osg::StateAttribute::OFF);
            state->setMode(GL_CULL_FACE,p.value("doubleSided",false)?osg::StateAttribute::OFF:osg::StateAttribute::ON);
            auto alpha=p.value("alphaMode",std::string("OPAQUE"));
            if(alpha=="MASK")state->setAttributeAndModes(new osg::AlphaFunc(osg::AlphaFunc::GEQUAL,p.value("alphaCutoff",0.5)),osg::StateAttribute::ON);
            if(alpha=="BLEND") {state->setAttributeAndModes(new osg::BlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA),osg::StateAttribute::ON);state->setRenderingHint(osg::StateSet::TRANSPARENT_BIN);}
            if(p.contains("texture")) {
                std::string file=p["texture"];
                auto image=osgDB::readRefImageFile(file);
                if(!image)throw std::runtime_error("Cannot decode image: "+file);
                auto texture=new osg::Texture2D(image);
                texture->setWrap(osg::Texture::WRAP_S,(osg::Texture::WrapMode)p.value("wrapS",10497));
                texture->setWrap(osg::Texture::WRAP_T,(osg::Texture::WrapMode)p.value("wrapT",10497));
                texture->setFilter(osg::Texture::MIN_FILTER,(osg::Texture::FilterMode)p.value("minFilter",9987));
                texture->setFilter(osg::Texture::MAG_FILTER,(osg::Texture::FilterMode)p.value("magFilter",9729));
                state->setTextureAttributeAndModes(0,texture,osg::StateAttribute::ON);
            }
            g->setUseDisplayList(false);g->setUseVertexBufferObjects(true);geo->addDrawable(g);
        }
    }
    auto children=new osg::Group;
    for(auto& child:job.value("children",json::array())) {
        if(geo->getNumDrawables() && child.contains("localFile")) {
            auto n=osgDB::readRefNodeFile(child["localFile"].get<std::string>());
            if(!n)throw std::runtime_error("Cannot load child coarse mesh");
            Rebase rebase(child.value("prefix",std::string("")));n->accept(rebase);children->addChild(n);
        } else children->addChild(reference(child));
    }
    osg::ref_ptr<osg::Group> root=new osg::Group;
    if(!children->getNumChildren())return geometry;
    if(!geo->getNumDrawables()) {root->addChild(children);return root;}
    // Page a single group of descendants, so REPLACE keeps its coarse mesh until
    // the group's page is loaded. Descendant nodes have their own paging bounds.
    auto lod=new osg::PagedLOD;
    lod->setCenterMode(osg::LOD::USER_DEFINED_CENTER);lod->setCenter(center(job));lod->setRadius(job.value("radius",1.0));
    lod->setRangeMode(osg::LOD::PIXEL_SIZE_ON_SCREEN);
    float threshold=job.value("threshold",256.0);
    bool add=job.value("refine",std::string("REPLACE"))=="ADD";
    lod->addChild(geometry,0,add?std::numeric_limits<float>::max():threshold);
    lod->setFileName(1,job.at("childrenPage").get<std::string>());lod->setRange(1,threshold,std::numeric_limits<float>::max());
    lod->setNumChildrenThatCannotBeExpired(1);
    std::string childOutput=job.at("childrenOutput");
    osg::ref_ptr<osgDB::Options> childOptions=new osgDB::Options;
    childOptions->setPluginStringData("WriteImageHint","IncludeData");
    if(!osgDB::writeNodeFile(*children,childOutput,childOptions))throw std::runtime_error("Cannot write child page");
    return lod;
}

struct Inspect:osg::NodeVisitor {
    uint64_t vertices=0,triangles=0,textures=0;json refs=json::array();osg::BoundingBoxd box;
    Inspect():NodeVisitor(TRAVERSE_ALL_CHILDREN){}
    void apply(osg::PagedLOD& n)override {for(unsigned i=0;i<n.getNumFileNames();i++)if(!n.getFileName(i).empty())refs.push_back(n.getFileName(i));traverse(n);}
    void apply(osg::Geode& n)override {
        for(unsigned i=0;i<n.getNumDrawables();i++) {
            auto g=n.getDrawable(i)->asGeometry();if(!g)continue;
            auto xyz=dynamic_cast<osg::Vec3Array*>(g->getVertexArray());
            if(xyz){vertices+=xyz->size();for(auto& v:*xyz)box.expandBy(osg::Vec3d(v));}
            for(unsigned k=0;k<g->getNumPrimitiveSets();k++)triangles+=g->getPrimitiveSet(k)->getNumIndices()/3;
            auto s=g->getStateSet();auto t=s?dynamic_cast<osg::Texture2D*>(s->getTextureAttribute(0,osg::StateAttribute::TEXTURE)):nullptr;
            if(t&&t->getImage()&&t->getImage()->data())textures++;
        }traverse(n);
    }
};

int main(int argc,char**argv) {
    try {
        if(argc<3)throw std::runtime_error("Usage: mesh_writer write job.json | inspect file.osgb");
        osg::setNotifyLevel(osg::WARN);
        if(std::string(argv[1])=="inspect") {
            auto node=osgDB::readRefNodeFile(argv[2]);if(!node)throw std::runtime_error("Cannot read OSGB");
            Inspect v;node->accept(v);json j={{"vertices",v.vertices},{"triangles",v.triangles},{"textures",v.textures},{"references",v.refs}};
            if(v.box.valid())j["bounds"]={{v.box.xMin(),v.box.yMin(),v.box.zMin()},{v.box.xMax(),v.box.yMax(),v.box.zMax()}};
            std::cout<<j.dump()<<std::endl;return 0;
        }
        std::ifstream f(fs::u8path(argv[2]));json job;f>>job;
        auto root=create(job);osg::ref_ptr<osgDB::Options> options=new osgDB::Options;
        options->setPluginStringData("WriteImageHint","IncludeFile");
        std::string output=job.at("output");
        if(!osgDB::writeNodeFile(*root,output,options))throw std::runtime_error("Cannot write OSGB");
        std::cout<<"{\"ok\":true}"<<std::endl;
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
