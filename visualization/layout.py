"""A compact paper-and-ocean shell matching the user's reference laboratory."""
import reacton.ipyvuetify as v
import solara
from solara.components.applayout import sidebar_portal


@solara.component_vue('viewport.vue')
def ResetSceneViewport(epoch:str):
    pass


@solara.component
def LaboratoryLayout(children=[]):
    opened,set_opened=solara.use_state(True)
    sidebar=sidebar_portal.use_portal()
    with v.Html(tag='div',style_='height:100vh') as root:
        if sidebar:
            with v.NavigationDrawer(app=True,clipped=True,width=296,v_model=opened,on_v_model=set_opened,
                                    mobile_break_point=960,disable_route_watcher=True,class_='lab-sidebar'):
                v.Html(tag='div',children=sidebar,class_='lab-sidebar-content')
        with v.AppBar(app=True,height=88,clipped_left=True,dark=False,class_='lab-masthead'):
            solara.Button(icon_name='mdi-menu',icon=True,on_click=lambda:set_opened(not opened))
            with v.Html(tag='div',class_='lab-brand'):
                v.Html(tag='span',class_='lab-brand-mark',children=['≋'])
                with v.Html(tag='span',class_='lab-brand-name'):
                    v.Html(tag='span',children=['群体动力学实验室'])
                    v.Html(tag='small',children=['COLLECTIVE DYNAMICS LAB'])
            v.Spacer()
            with v.Html(tag='div',class_='lab-connection'):
                v.Html(tag='i')
                v.Html(tag='span',children=['INDIVIDUALS / INTERACTIONS / COLLECTIVE DYNAMICS'])
        with v.Content(style_='height:100%'):
            solara.Div(children=children,classes=['lab-main'])
    return root
